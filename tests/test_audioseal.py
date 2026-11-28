"""The real AudioSeal watermark, end to end.

Downloads the AudioSeal weights, so it only runs on request:

    OMNISUITE_TEST_AUDIOSEAL=1 python -m pytest tests/test_audioseal.py
"""

import os

import numpy as np
import pytest
import soundfile as sf

import receipts
from conftest import SAMPLE_RATE, speechlike

pytestmark = pytest.mark.skipif(
    not os.environ.get("OMNISUITE_TEST_AUDIOSEAL"),
    reason="downloads the AudioSeal weights; set OMNISUITE_TEST_AUDIOSEAL=1 to run",
)


@pytest.fixture(scope="module")
def watermark():
    return receipts.AudioSealWatermark()


def test_tag_round_trip_at_24_khz(watermark):
    audio = speechlike(6.0)[None, :]
    marked = watermark.embed(audio, SAMPLE_RATE, 0xA53C)
    assert marked.shape == audio.shape

    score, tag = watermark.detect(marked, SAMPLE_RATE)
    assert score > 0.9
    assert tag == 0xA53C

    # The mark has to stay well below the speech.
    noise = marked - audio
    snr = 10 * np.log10((audio**2).mean() / (noise**2).mean())
    assert snr > 20


def test_unmarked_audio_is_not_flagged(watermark):
    score, _ = watermark.detect(speechlike(6.0, seed=3)[None, :], SAMPLE_RATE)
    assert score < receipts.DETECTION_THRESHOLD


def test_file_is_traced_after_the_manifest_is_gone(watermark, tmp_path):
    marker = receipts.Marker(tmp_path / "data", watermark=watermark)
    wav_bytes, receipt = marker.mark(speechlike(6.0), SAMPLE_RATE, model="test/model")
    path = tmp_path / "clip.wav"
    path.write_bytes(wav_bytes)

    intact = receipts.verify_file(path, tmp_path / "data", watermark=watermark)
    assert intact["verdict"] == "intact"
    assert intact["watermark"]["matches_receipt"] is True

    # FLAC keeps the samples and drops the manifest.
    audio, sample_rate = sf.read(path, dtype="int16")
    flac = tmp_path / "clip.flac"
    sf.write(flac, audio, sample_rate)
    stripped = receipts.verify_file(flac, tmp_path / "data", watermark=watermark)
    assert stripped["verdict"] == "stripped"
    assert stripped["watermark"]["receipts_here"][0]["id"] == receipt["id"]
