"""Run Retake on the RealEdit benchmark and score it.

    python experiments/retake/realedit.py \
        --manifest experiments/retake/data/RealEdit.txt \
        --audio-root experiments/retake/data/audio \
        --out experiments/retake/out

For every clip it finds the changed words, times them in the recording with a
forced aligner, lets Retake re-render them, and transcribes the result with
Whisper. It writes the audio, a results table, a summary and a page for
listening. README.md says how to read the numbers.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import html
import json
import string
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from retake import Edit

# Changes closer together than this are re-rendered as one, words between included.
MIN_KEEP_SECONDS = 0.3
AUDIO_SUFFIXES = {".wav", ".flac", ".ogg", ".mp3"}


@dataclass
class Row:
    name: str  # audio file name
    before: str
    after: str
    kind: str  # substitution, deletion, insertion, or several joined by "|"


def read_manifest(path: Path) -> list[Row]:
    """RealEdit.txt: tab-separated with a header line.

    Columns: wav_fn, orig_transcript, new_transcript, orig_masked_span,
    new_masked_span, type. A clip edited in several steps lists every step in
    new_transcript, separated by "|"; the last one is the target.
    """
    rows = []
    with open(path, encoding="utf-8") as handle:
        lines = [line.rstrip("\n") for line in handle if line.strip()]
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) < 6:
            raise ValueError(f"Expected 6 tab-separated columns, got: {line!r}")
        rows.append(
            Row(
                name=Path(cells[0]).name,
                before=cells[1].strip(),
                after=cells[2].split("|")[-1].strip(),
                kind=cells[5].strip(),
            )
        )
    return rows


def changes(before: list[str], after: list[str]) -> list[tuple[int, int, int, int]]:
    """Word ranges that differ: (i1, i2, j1, j2) says before[i1:i2] becomes after[j1:j2]."""
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return [
        (i1, i2, j1, j2)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def to_edits(
    before: list[str],
    after: list[str],
    times: list[tuple[float, float]],
    clip_seconds: float,
) -> list[Edit]:
    """The changes between two transcripts as edits in seconds.

    ``times[i]`` is the start and end of ``before[i]`` in the recording. Words
    put in between two words take the pause between them, as in VoiceCraft's
    own RealEdit script.
    """
    spans = []  # start, end, j1, j2
    for i1, i2, j1, j2 in changes(before, after):
        if i1 < i2:
            start, end = times[i1][0], times[i2 - 1][1]
        else:
            start = times[i1 - 1][1] if i1 > 0 else 0.0
            end = times[i1][0] if i1 < len(before) else clip_seconds
            end = max(start, end)
        if spans and start - spans[-1][1] < MIN_KEEP_SECONDS:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]), spans[-1][2], j2)
        else:
            spans.append((start, end, j1, j2))
    return [Edit(start, end, " ".join(after[j1:j2])) for start, end, j1, j2 in spans]


def normalise(text: str) -> list[str]:
    """Lower-case words without punctuation; apostrophes stay."""
    for mark in string.punctuation:
        if mark != "'":
            text = text.replace(mark, " ")
    return text.lower().split()


def word_errors(reference: list[str], hypothesis: list[str]) -> int:
    """Fewest word substitutions, deletions and insertions between the two."""
    row = list(range(len(hypothesis) + 1))
    for i, ref_word in enumerate(reference, start=1):
        previous, row[0] = row[0], i
        for j, hyp_word in enumerate(hypothesis, start=1):
            previous, row[j] = row[j], min(
                row[j] + 1, row[j - 1] + 1, previous + (ref_word != hyp_word)
            )
    return row[-1]


class Aligner:
    """Times each word of a known transcript in a recording (torchaudio MMS_FA)."""

    def __init__(self, device):
        import torchaudio

        bundle = torchaudio.pipelines.MMS_FA
        self.rate = bundle.sample_rate
        self.device = device
        self.model = bundle.get_model().to(device).eval()
        self.dictionary = bundle.get_dict()
        self.align = bundle.get_aligner()

    def spell(self, word: str) -> list[int]:
        letters = [c for c in word.lower() if c in self.dictionary and c not in "-*"]
        # "*" stands in for anything the aligner has no letters for, such as digits.
        return [self.dictionary[c] for c in letters] or [self.dictionary["*"]]

    def __call__(self, audio: np.ndarray, rate: int, words: list[str]):
        import torch
        import torchaudio

        wav = torch.from_numpy(audio)[None]
        wav = torchaudio.functional.resample(wav, rate, self.rate)
        with torch.inference_mode():
            emission, _ = self.model(wav.to(self.device))
        spans = self.align(emission[0].float().cpu(), [self.spell(w) for w in words])
        seconds = wav.shape[1] / emission.shape[1] / self.rate
        return [(span[0].start * seconds, span[-1].end * seconds) for span in spans]


class Transcriber:
    """Whisper large-v3, the usual judge for word error rate on English speech."""

    def __init__(self, device, model_name="openai/whisper-large-v3"):
        import torch
        import transformers

        self.pipe = transformers.pipeline(
            "automatic-speech-recognition",
            model=model_name,
            dtype=torch.float16 if "cuda" in str(device) else torch.float32,
            device=device,
        )

    def __call__(self, audio: np.ndarray, rate: int) -> str:
        import torch
        import torchaudio

        wav = torchaudio.functional.resample(torch.from_numpy(audio), rate, 16000)
        out = self.pipe(
            {"array": wav.numpy(), "sampling_rate": 16000},
            chunk_length_s=30,
            generate_kwargs={"language": "english", "task": "transcribe"},
        )
        return out["text"].strip()


def load_audio(path: Path, rate: int) -> np.ndarray:
    import soundfile
    import torch
    import torchaudio

    samples, file_rate = soundfile.read(path, dtype="float32", always_2d=True)
    mono = torch.from_numpy(samples.mean(axis=1))
    return torchaudio.functional.resample(mono, file_rate, rate).numpy()


def summarise(results: list[dict]) -> dict:
    """Word error rate over all clips together, and per kind of edit."""

    def rate(rows, key):
        words = sum(r["words_" + key] for r in rows)
        return round(100 * sum(r["errors_" + key] for r in rows) / max(words, 1), 2)

    def block(rows):
        return {
            "clips": len(rows),
            "wer_retake": rate(rows, "retake"),
            "wer_original": rate(rows, "original"),
        }

    summary = {"all": block(results)}
    for kind in sorted({r["kind"] for r in results}):
        summary[kind] = block([r for r in results if r["kind"] == kind])
    return summary


def write_listening_page(path: Path, results: list[dict]) -> None:
    rows = []
    for r in results:
        rows.append(
            "<tr><td>{id}<br>{kind}</td><td>{before}<br><b>{after}</b></td>"
            '<td><audio controls preload="none" src="audio/{id}.original.wav"></audio>'
            '<br><audio controls preload="none" src="audio/{id}.retake.wav"></audio></td>'
            "<td>{heard}<br>{errors_retake} errors, edit at {at}</td></tr>".format(
                id=html.escape(r["id"]),
                kind=html.escape(r["kind"]),
                before=html.escape(r["before"]),
                after=html.escape(r["after"]),
                heard=html.escape(r["heard_retake"]),
                errors_retake=r["errors_retake"],
                at=html.escape(r["edit_seconds"]),
            )
        )
    page = (
        '<!doctype html><meta charset="utf-8"><title>Retake on RealEdit</title>'
        "<style>body{font:14px system-ui;margin:2rem}td{padding:.5rem;"
        "border-top:1px solid #ccc;vertical-align:top}</style>"
        "<h1>Retake on RealEdit</h1><p>Top player: original. Bottom player: retake. "
        "Listen for a click, a jump in loudness or a change of voice at the edit.</p>"
        "<table>" + "".join(rows) + "</table>"
    )
    path.write_text(page, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--manifest", type=Path, required=True, help="RealEdit.txt")
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default=None, help="cuda or cpu (default: cuda if there)")
    parser.add_argument("--limit", type=int, default=None, help="only the first N clips")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--margin", type=float, default=0.08)
    parser.add_argument(
        "--decode-all",
        action="store_true",
        help="decode the whole clip from tokens and keep no original samples",
    )
    args = parser.parse_args(argv)

    import soundfile
    import torch
    from omnivoice import OmniVoice

    from retake import retake

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    rows = read_manifest(args.manifest)
    files = {
        p.stem: p
        for p in args.audio_root.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES
    }
    found = [row for row in rows if Path(row.name).stem in files]
    print(f"{len(rows)} clips in the manifest, audio found for {len(found)}")
    if args.limit:
        found = found[: args.limit]
    if not found:
        return 1

    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=torch.float16 if device == "cuda" else torch.float32,
    )
    aligner = Aligner(device)
    transcriber = Transcriber(device)
    rate = model.sampling_rate
    frame_seconds = model.audio_tokenizer.config.hop_length / rate

    audio_dir = args.out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    results, failed = [], []
    for index, row in enumerate(found):
        clip = Path(row.name).stem
        try:
            audio = load_audio(files[clip], rate)
            before, after = row.before.split(), row.after.split()
            times = aligner(audio, rate, before)
            edits = to_edits(before, after, times, len(audio) / rate)
            if not edits:
                raise ValueError("The two transcripts are the same")

            torch.manual_seed(args.seed + index)
            result = retake(
                model,
                audio,
                row.before,
                row.after,
                edits,
                lang="en",
                margin=args.margin,
                keep_original=not args.decode_all,
            )
            soundfile.write(audio_dir / f"{clip}.original.wav", audio, rate)
            soundfile.write(audio_dir / f"{clip}.retake.wav", result.audio, rate)

            heard_original = transcriber(audio, rate)
            heard_retake = transcriber(result.audio, rate)
            reference_before, reference_after = normalise(row.before), normalise(row.after)
            results.append(
                {
                    "id": clip,
                    "kind": row.kind,
                    "before": row.before,
                    "after": row.after,
                    "heard_original": heard_original,
                    "heard_retake": heard_retake,
                    "words_original": len(reference_before),
                    "errors_original": word_errors(reference_before, normalise(heard_original)),
                    "words_retake": len(reference_after),
                    "errors_retake": word_errors(reference_after, normalise(heard_retake)),
                    "edit_seconds": " ".join(
                        f"{g.new_start * frame_seconds:.2f}-{g.new_end * frame_seconds:.2f}"
                        for g in result.gaps
                    ),
                    "confidence": round(result.confidence, 3),
                }
            )
            print(f"[{index + 1}/{len(found)}] {clip}: {results[-1]['errors_retake']} errors")
        except Exception as error:  # one broken clip must not end the run
            traceback.print_exc()
            failed.append({"id": clip, "error": repr(error)})

    if results:
        with open(args.out / "results.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        write_listening_page(args.out / "listen.html", results)
    summary = {
        "settings": {
            "model": args.model,
            "device": device,
            "seed": args.seed,
            "margin": args.margin,
            "keeps_original_samples": not args.decode_all,
        },
        "clips_in_manifest": len(rows),
        "clips_without_audio": sum(Path(r.name).stem not in files for r in rows),
        "clips_failed": failed,
        "wer_percent": summarise(results) if results else {},
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["wer_percent"], indent=2))
    print(f"{len(failed)} clips failed. Listen: {args.out / 'listen.html'}")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
