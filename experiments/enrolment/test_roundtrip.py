"""The round trip's own plumbing, with stand-ins for the model and for enrolment.py."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import io

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("roundtrip", HERE / "roundtrip.py")
roundtrip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roundtrip)


class Enrolment:
    """Just enough of enrolment.py."""

    def __init__(self):
        self.made = 0

    def make_sentence(self, language):
        self.made += 1
        return f"Sentence number {'one two three four five'.split()[self.made % 5]} in {language}."

    @staticmethod
    def words(text):
        return "".join(ch if ch.isalpha() else " " for ch in text.lower()).split()

    def read_take(self, content):
        audio, rate = sf.read(io.BytesIO(content), dtype="float32")
        return audio, rate

    def matches(self, sentence, heard):
        same = self.words(sentence) == self.words(heard)
        return same, 1.0 if same else 0.5


class Model:
    def __init__(self, mishear=()):
        self.mishear = mishear
        self.said = None

    def generate(self, text, language):
        self.said = text
        if "three" in text and "three" in self.mishear:
            raise RuntimeError("no audio today")
        return [0.1 * np.ones(roundtrip.RATE, dtype=np.float32)]

    def transcribe(self, audio):
        take, rate = audio
        assert rate == roundtrip.RATE and len(take) > roundtrip.RATE
        return self.said.replace("two", "too") if "two" in self.mishear else self.said


def test_every_sentence_is_read_heard_and_judged():
    rows = roundtrip.run(Model(), Enrolment(), ["en", "de"], 4)
    assert len(rows) == 8
    assert all(row["passed"] and not row["error"] for row in rows)
    assert not any(row["passed_for_another"] for row in rows)

    summary = roundtrip.summarise(rows)
    assert summary["en"]["passed"] == summary["en"]["sentences"] == 4
    assert summary["de"]["mean_seconds"] > 1.0


def test_misheard_words_and_failures_are_counted():
    rows = roundtrip.run(Model(mishear=("two", "three")), Enrolment(), ["en"], 5)
    summary = roundtrip.summarise(rows)["en"]
    assert summary["passed"] == 3
    assert summary["errors"] == 1
    assert summary["words_missed_most"] == [("two", 1)]
    assert [row["error"] for row in rows if row["error"]] == ["RuntimeError: no audio today"]


def test_enrolment_is_loaded_by_path(tmp_path):
    (tmp_path / "enrolment.py").write_text("ANSWER = 42\n")
    assert roundtrip.load_module(tmp_path / "enrolment.py").ANSWER == 42
    del sys.modules["enrolment"]
