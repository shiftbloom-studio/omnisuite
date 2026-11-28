"""Long audio is watermarked and read in pieces. The model is faked, the stitching is real."""

import numpy as np
import torch

import receipts


class ConstantGenerator:
    """Returns the same watermark value everywhere, so seams would show."""

    def __init__(self):
        self.piece_lengths = []

    def get_watermark(self, piece, sample_rate, message):
        self.piece_lengths.append(piece.shape[-1])
        return torch.full_like(piece, 0.1)


class HalfMarkedDetector:
    """Says the first piece is watermarked with all ones and the rest is clean."""

    def __init__(self):
        self.calls = 0

    def __call__(self, piece, sample_rate):
        self.calls += 1
        marked = self.calls == 1
        presence = torch.zeros(1, 2, piece.shape[-1])
        presence[:, 1 if marked else 0] = 1.0
        return presence, torch.full((1, receipts.WATERMARK_BITS), 1.0 if marked else 0.4)


def test_pieces_join_without_a_seam():
    watermark = receipts.AudioSealWatermark()
    watermark._generator = ConstantGenerator()
    seconds = 45
    silence = np.zeros((1, seconds * receipts.WATERMARK_RATE), dtype=np.float32)

    marked = watermark.embed(silence, receipts.WATERMARK_RATE, 0)

    assert len(watermark._generator.piece_lengths) == 3
    assert max(watermark._generator.piece_lengths) == receipts.WATERMARK_CHUNK
    assert marked.shape == silence.shape
    np.testing.assert_allclose(marked, 0.1, atol=1e-6)


def test_short_audio_is_one_piece():
    watermark = receipts.AudioSealWatermark()
    watermark._generator = ConstantGenerator()
    marked = watermark.embed(np.zeros((2, 1000), dtype=np.float32), receipts.WATERMARK_RATE, 0)
    assert watermark._generator.piece_lengths == [1000]
    np.testing.assert_allclose(marked, 0.1, atol=1e-6)


def test_detection_is_weighted_over_the_pieces():
    watermark = receipts.AudioSealWatermark()
    watermark._detector = HalfMarkedDetector()
    audio = np.zeros((1, 2 * receipts.WATERMARK_CHUNK), dtype=np.float32)

    score, tag = watermark.detect(audio, receipts.WATERMARK_RATE)

    assert watermark._detector.calls == 2
    assert score == 0.5
    assert tag == 0xFFFF  # (1.0 + 0.4) / 2 is still above one half
