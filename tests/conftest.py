"""Shared test helpers."""

import numpy as np
import pytest

import receipts

SAMPLE_RATE = 24000


class FakeWatermark:
    """Stands in for AudioSeal: writes the tag into the first 32 samples."""

    PREAMBLE = [1.0, -1.0] * 8

    def load(self):
        pass

    def embed(self, audio, sample_rate, tag):
        out = np.array(audio, dtype=np.float32, copy=True)
        bits = [(tag >> (15 - i)) & 1 for i in range(16)]
        out[:, :16] = 0.25 * np.array(self.PREAMBLE)
        out[:, 16:32] = [0.25 if bit else -0.25 for bit in bits]
        return out

    def detect(self, audio, sample_rate):
        head = audio.mean(axis=0)[:32]
        if len(head) < 32 or list(np.sign(head[:16])) != self.PREAMBLE:
            return 0.0, 0
        tag = 0
        for value in head[16:]:
            tag = (tag << 1) | int(value > 0)
        return 1.0, tag


def speechlike(seconds=4.0, sample_rate=SAMPLE_RATE, seed=0):
    """A voiced, syllable-shaped signal: closer to speech than a plain sine."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    pitch = 120 + 30 * np.sin(2 * np.pi * 0.7 * t) + 10 * np.sin(2 * np.pi * 2.3 * t)
    phase = 2 * np.pi * np.cumsum(pitch) / sample_rate
    voiced = np.zeros_like(t)
    for harmonic in range(1, 40):
        frequency = harmonic * 120
        # Three rough formants shape the harmonics.
        gain = sum(
            np.exp(-(((frequency - formant) / width) ** 2))
            for formant, width in ((600, 250), (1500, 350), (2600, 500))
        )
        voiced += (gain + 0.02) * np.sin(harmonic * phase)
    syllables = 0.5 * (1 + np.sin(2 * np.pi * 4 * t - np.pi / 2))
    noise = 0.02 * rng.standard_normal(len(t))
    signal = voiced / np.abs(voiced).max() * syllables + noise
    return (0.4 * signal / np.abs(signal).max()).astype(np.float32)


@pytest.fixture(autouse=True)
def test_client_host(monkeypatch):
    """The test client calls the server as "testserver"."""
    import app as server

    monkeypatch.setattr(server, "ALLOWED_HOSTS", server.ALLOWED_HOSTS | {"testserver"})


@pytest.fixture
def marker(tmp_path):
    """A marker with its own data folder and no model download."""
    return receipts.Marker(tmp_path / "data", watermark=FakeWatermark())
