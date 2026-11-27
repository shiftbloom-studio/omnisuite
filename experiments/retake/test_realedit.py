"""Tests for realedit.py: the parts that need no model, and one dry run."""

import csv
import json

import numpy as np
import soundfile

import realedit
from conftest import HOP, RATE
from realedit import (
    changes,
    normalise,
    read_manifest,
    summarise,
    to_edits,
    word_errors,
    write_listening_page,
)
from retake import Edit

HEADER = "wav_fn\torig_transcript\tnew_transcript\torig_masked_span\tnew_masked_span\ttype\n"


def timed(words, each=0.4, pause=0.1):
    """Every word takes ``each`` seconds, with ``pause`` seconds after it."""
    return [(i * (each + pause), i * (each + pause) + each) for i in range(len(words))]


def test_manifest_takes_the_last_step_as_the_target(tmp_path):
    path = tmp_path / "RealEdit.txt"
    path.write_text(
        HEADER
        + "a/clip_1.wav\tone two three\tone four three\t1\t1\tsubstitution\n"
        + "clip_2.wav\tone two\tone big two|one big blue two\t0,1|1,2\t1|2\tinsertion|insertion\n",
        encoding="utf-8",
    )
    first, second = read_manifest(path)
    assert (first.name, first.before, first.after) == ("clip_1.wav", "one two three", "one four three")
    assert first.kind == "substitution"
    assert second.after == "one big blue two"
    assert second.kind == "insertion|insertion"


def test_changes_names_the_word_ranges_that_differ():
    before = "the quick brown fox".split()
    assert changes(before, "the slow brown fox".split()) == [(1, 2, 1, 2)]
    assert changes(before, "the brown fox".split()) == [(1, 2, 1, 1)]
    assert changes(before, "the quick brown red fox".split()) == [(3, 3, 3, 4)]
    assert changes(before, before) == []


def test_a_substitution_spans_the_old_words():
    before = "the quick brown fox".split()
    after = "the very slow brown fox".split()
    assert to_edits(before, after, timed(before), 2.0) == [Edit(0.5, 0.9, "very slow")]


def test_a_deletion_has_no_words():
    before = "the quick brown fox".split()
    assert to_edits(before, "the brown fox".split(), timed(before), 2.0) == [Edit(0.5, 0.9, "")]


def test_an_insertion_takes_the_pause_between_its_neighbours():
    before = "the quick brown fox".split()
    after = "the quick brown red fox".split()
    (edit,) = to_edits(before, after, timed(before), 2.0)
    assert (round(edit.start, 3), round(edit.end, 3), edit.words) == (1.4, 1.5, "red")


def test_insertions_at_either_end_take_the_silence_there():
    before = "quick brown".split()
    times = [(0.3, 0.7), (0.8, 1.2)]
    assert to_edits(before, "the quick brown".split(), times, 1.5) == [Edit(0.0, 0.3, "the")]
    assert to_edits(before, "quick brown fox".split(), times, 1.5) == [Edit(1.2, 1.5, "fox")]


def test_changes_close_together_become_one_edit():
    before = "a b c d e f".split()
    after = "a x c y e f".split()
    # Spoken fast, "c" and the pauses around it last 0.25 s: too short to keep.
    (edit,) = to_edits(before, after, timed(before, each=0.15, pause=0.05), 3.0)
    assert (round(edit.start, 3), round(edit.end, 3), edit.words) == (0.2, 0.75, "x c y")


def test_changes_far_apart_stay_separate():
    before = "a b c d e f".split()
    after = "a x c d e y".split()
    first, second = to_edits(before, after, timed(before), 3.0)
    assert (first.words, second.words) == ("x", "y")


def test_word_errors_counts_the_fewest_changes():
    reference = normalise("The quick, brown fox - doesn't it?")
    assert reference == ["the", "quick", "brown", "fox", "doesn't", "it"]
    assert word_errors(reference, reference) == 0
    assert word_errors(reference, normalise("the quick fox doesn't it")) == 1
    assert word_errors(reference, normalise("a quick brown fox doesn't do it")) == 2
    assert word_errors(reference, []) == 6
    assert word_errors([], reference) == 6


def result(kind, errors_retake, errors_original=0):
    return {
        "id": "clip<1>",
        "kind": kind,
        "before": "a & b",
        "after": "a & c",
        "heard_retake": "a and c",
        "edit_seconds": "0.50-0.90",
        "words_original": 10,
        "errors_original": errors_original,
        "words_retake": 10,
        "errors_retake": errors_retake,
    }


def test_summary_pools_the_words_of_all_clips():
    summary = summarise([result("insertion", 1), result("deletion", 3, 1)])
    assert summary["all"] == {"clips": 2, "wer_retake": 20.0, "wer_original": 5.0}
    assert summary["deletion"]["wer_retake"] == 30.0


def test_listening_page_escapes_what_it_shows(tmp_path):
    page = tmp_path / "listen.html"
    write_listening_page(page, [result("insertion", 1)])
    text = page.read_text(encoding="utf-8")
    assert "clip&lt;1&gt;" in text and "a &amp; c" in text
    assert 'src="audio/clip&lt;1&gt;.retake.wav"' in text


def test_a_run_writes_audio_scores_and_the_listening_page(tmp_path, model, monkeypatch):
    """The whole run with stand-ins for the three models."""

    class EvenAligner:
        def __init__(self, device):
            pass

        def __call__(self, audio, rate, words):
            each = len(audio) / rate / len(words)
            return [(i * each, (i + 1) * each) for i in range(len(words))]

    class Echo:
        """Hears the original as spoken and every retake as "one seven three"."""

        def __init__(self, device):
            self.heard = iter(["One two three.", "one seven three", "one two", "one seven three"])

        def __call__(self, audio, rate):
            return next(self.heard)

    monkeypatch.setattr(realedit, "Aligner", EvenAligner)
    monkeypatch.setattr(realedit, "Transcriber", Echo)
    monkeypatch.setattr(
        "omnivoice.OmniVoice.from_pretrained", classmethod(lambda cls, *a, **k: model)
    )

    audio_root = tmp_path / "audio" / "nested"
    audio_root.mkdir(parents=True)
    clip = np.full(75 * HOP, 0.3, dtype=np.float32)
    soundfile.write(audio_root / "clip_1.wav", clip, RATE)
    soundfile.write(audio_root / "clip_2.wav", clip, RATE)
    manifest = tmp_path / "RealEdit.txt"
    manifest.write_text(
        HEADER
        + "clip_1.wav\tone two three\tone seven three\t1\t1\tsubstitution\n"
        + "clip_2.wav\tone two three\tone three\t1\t0,1\tdeletion\n"
        + "clip_3.wav\tone two three\tone three\t1\t0,1\tdeletion\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"

    code = realedit.main(
        ["--manifest", str(manifest), "--audio-root", str(tmp_path / "audio"),
         "--out", str(out), "--device", "cpu"]
    )

    assert code == 0
    for name in ("clip_1.original.wav", "clip_1.retake.wav", "clip_2.retake.wav"):
        assert (out / "audio" / name).stat().st_size > 1000
    with open(out / "results.csv", newline="", encoding="utf-8") as handle:
        first, second = csv.DictReader(handle)
    assert (first["errors_original"], first["errors_retake"]) == ("0", "0")
    assert (second["errors_original"], second["errors_retake"]) == ("1", "1")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["clips_in_manifest"] == 3
    assert summary["clips_without_audio"] == 1
    assert summary["clips_failed"] == []
    assert summary["wer_percent"]["all"]["clips"] == 2
    assert summary["wer_percent"]["deletion"]["wer_retake"] == 50.0
    assert "clip_2.retake.wav" in (out / "listen.html").read_text(encoding="utf-8")
