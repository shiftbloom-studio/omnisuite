"""Does Whisper give back the enrolment sentences word for word?

Enrolment by reading compares what Whisper hears with a sentence OmniSuite made
up. That only works if Whisper writes the words the way the sentence spells
them. This reads many made-up sentences with OmniVoice, puts each through the
same steps a real take goes through, and counts how many pass.

A model reads here, not a person at a microphone, so real takes will do a bit
worse. What this finds is words Whisper keeps spelling another way.

    python experiments/enrolment/roundtrip.py --enrolment path/to/enrolment.py --out out
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 24000  # what OmniVoice writes


def load_module(path: Path):
    """enrolment.py lives on another branch, so it is loaded by path."""
    spec = importlib.util.spec_from_file_location("enrolment", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["enrolment"] = module
    spec.loader.exec_module(module)
    return module


def as_take(audio: np.ndarray, rng: np.random.Generator) -> bytes:
    """The speech as a recording: a wait before and after it, with a little room noise."""
    def room(seconds):
        return 0.001 * rng.standard_normal(int(seconds * RATE))

    take = np.concatenate([room(0.8), np.asarray(audio, dtype=np.float32), room(0.6)])
    buffer = io.BytesIO()
    sf.write(buffer, take.astype(np.float32), RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def differing_words(enrolment, sentence: str, heard: str) -> list[str]:
    """Words of the sentence that Whisper did not write, by simple set difference."""
    written = set(enrolment.words(heard))
    return [word for word in enrolment.words(sentence) if word not in written]


def run(model, enrolment, languages, count, seed=1) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for language in languages:
        previous = None
        for number in range(count):
            sentence = enrolment.make_sentence(language)
            row = {"language": language, "sentence": sentence}
            try:
                audio = model.generate(text=sentence, language=language)[0]
                take, rate = enrolment.read_take(as_take(audio, rng))
                heard = model.transcribe((take, rate))
                passed, score = enrolment.matches(sentence, heard)
                row.update(
                    seconds=round(len(take) / rate, 2),
                    heard=heard,
                    passed=passed,
                    score=score,
                    missed=" ".join(differing_words(enrolment, sentence, heard)),
                    # The same take must not pass for the sentence before it.
                    passed_for_another=bool(previous)
                    and enrolment.matches(previous, heard)[0],
                    error="",
                )
            except Exception as error:  # one bad sentence must not end the run
                row.update(
                    seconds=0.0,
                    heard="",
                    passed=False,
                    score=0.0,
                    missed="",
                    passed_for_another=False,
                    error=f"{type(error).__name__}: {error}",
                )
            rows.append(row)
            previous = sentence
            print(f"{language} {number + 1}/{count} {'ok  ' if row['passed'] else 'FAIL'} {row['score']}")
    return rows


def summarise(rows: list[dict]) -> dict:
    summary = {}
    for language in sorted({row["language"] for row in rows}):
        mine = [row for row in rows if row["language"] == language]
        missed = Counter(word for row in mine for word in row["missed"].split())
        summary[language] = {
            "sentences": len(mine),
            "passed": sum(row["passed"] for row in mine),
            "errors": sum(bool(row["error"]) for row in mine),
            "passed_for_another_sentence": sum(row["passed_for_another"] for row in mine),
            "mean_score": round(float(np.mean([row["score"] for row in mine])), 3),
            "mean_seconds": round(float(np.mean([row["seconds"] for row in mine])), 2),
            "words_missed_most": missed.most_common(15),
        }
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--enrolment", type=Path, required=True, help="path to enrolment.py")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=40, help="sentences per language")
    parser.add_argument("--languages", default="en,de")
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default=None, help="cuda or cpu (default: cuda if there)")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    import torch
    from omnivoice import OmniVoice

    enrolment = load_module(args.enrolment)
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(args.seed)
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=torch.float16 if device == "cuda" else torch.float32,
    )
    model.load_asr_model()

    started = time.time()
    rows = run(model, enrolment, args.languages.split(","), args.count, args.seed)
    summary = summarise(rows)
    summary["run"] = {"device": device, "seconds": round(time.time() - started, 1)}

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
