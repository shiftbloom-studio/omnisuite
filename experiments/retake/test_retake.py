"""Plumbing tests for retake.py with a tiny untrained model and a stand-in codec.

They check shapes, bookkeeping and that context is left alone. They say nothing
about how an edit sounds. Run with: python -m pytest experiments/retake
"""

import numpy as np
import torch
from omnivoice.models.omnivoice import OmniVoiceGenerationConfig

from conftest import HOP, RATE
from retake import Edit, Gap, infill, plan_gaps, retake, splice

FRAMES_PER_SECOND = RATE / HOP


def steps(count):
    return OmniVoiceGenerationConfig(num_step=count)


def staircase(frames):
    """A clip whose level names its frame: frame 7 sits at 0.207."""
    return np.repeat((200 + np.arange(frames, dtype=np.float32)) / 1000, HOP)


def test_infill_fills_only_the_masked_cells(model):
    mask = model.config.audio_mask_id
    known = torch.randint(0, 1024, (8, 30))
    known[:, 10:18] = mask

    filled, confidence = infill(model, known, "some words", gen_config=steps(6))

    assert filled.shape == known.shape
    assert not (filled == mask).any()
    context = known != mask
    assert torch.equal(filled[context], known[context])
    assert (confidence[context] == 0).all()
    assert (confidence[~context] < 0).all()


def test_infill_with_nothing_to_fill_returns_the_input(model):
    known = torch.randint(0, 1024, (8, 12))
    filled, confidence = infill(model, known, "some words", gen_config=steps(4))
    assert torch.equal(filled, known)
    assert (confidence == 0).all()


def plan(edits, frames=100, frames_per_weight=1.0):
    return plan_gaps(
        edits,
        frames,
        FRAMES_PER_SECOND,
        frames_per_weight,
        weigh=len,
        margin=0.08,
    )


def test_a_substitution_gets_room_for_the_new_words():
    # 1.0 s to 1.4 s is frames 25 to 35; the margin adds two frames on each side.
    (gap,) = plan([Edit(1.0, 1.4, "x" * 20)])
    assert (gap.old_start, gap.old_end) == (23, 37)
    assert gap.new_start == 23
    assert gap.new_end - gap.new_start == 20 + 4


def test_a_deletion_keeps_only_the_margins():
    (gap,) = plan([Edit(1.0, 1.4, "")])
    assert gap.new_end - gap.new_start == 4


def test_an_insertion_cuts_nothing_but_the_margins():
    (gap,) = plan([Edit(2.0, 2.0, "x" * 10)])
    assert (gap.old_start, gap.old_end) == (48, 52)
    assert gap.new_end - gap.new_start == 10 + 4


def test_later_gaps_move_with_earlier_edits():
    first, second = plan([Edit(3.0, 3.2, "x" * 5), Edit(1.0, 1.4, "")])
    assert first.old_start == 23  # sorted by time
    assert first.new_end - first.new_start == 4
    shift = (first.new_end - first.new_start) - (first.old_end - first.old_start)
    assert second.new_start == second.old_start + shift


def test_gaps_stay_inside_the_clip_and_never_overlap():
    first, second, third = plan(
        [Edit(0.0, 0.1, "a"), Edit(0.12, 0.3, "b"), Edit(9.0, 9.5, "c")], frames=100
    )
    assert first.old_start == 0
    assert second.old_start >= first.old_end
    assert third.old_start == third.old_end == 100


def test_splice_keeps_original_samples_outside_the_gaps():
    original = np.full(10 * HOP, 0.25, dtype=np.float32)
    decoded = np.full(12 * HOP, -0.5, dtype=np.float32)
    gaps = [Gap(old_start=4, old_end=6, new_start=4, new_end=8)]
    fade = 100

    out = splice(original, decoded, gaps, HOP, fade)

    assert len(out) == 12 * HOP
    assert (out[: 4 * HOP - fade] == 0.25).all()
    assert (out[4 * HOP : 8 * HOP] == -0.5).all()
    assert (out[8 * HOP + fade :] == 0.25).all()
    # The fades run from one level to the other without a jump.
    into = out[4 * HOP - fade : 4 * HOP]
    assert into[0] == 0.25 and into[-1] == -0.5
    assert (np.diff(into) <= 0).all()
    back = out[8 * HOP : 8 * HOP + fade]
    assert back[0] == -0.5 and back[-1] == 0.25
    assert (np.diff(back) >= 0).all()


def test_retake_changes_only_the_edited_span(model):
    audio = staircase(100)
    text_before = "one two three four five"
    text_after = "one two seven four five"

    result = retake(
        model,
        audio,
        text_before,
        text_after,
        [Edit(1.0, 1.4, "seven")],
        gen_config=steps(6),
    )

    (gap,) = result.gaps
    assert (gap.old_start, gap.old_end) == (23, 37)
    length = gap.new_end - gap.new_start
    assert len(result.audio) == (100 - 14 + length) * HOP
    fade = int(0.02 * RATE)
    head = gap.old_start * HOP - fade
    assert np.array_equal(result.audio[:head], audio[:head])
    tail = (100 - gap.old_end) * HOP - fade
    assert np.array_equal(result.audio[-tail:], audio[-tail:])
    assert result.confidence < 0


def test_retake_handles_two_edits_and_a_ragged_length(model):
    audio = np.concatenate([staircase(80), np.zeros(123, dtype=np.float32)])
    result = retake(
        model,
        audio,
        "one two three four five",
        "one three four six five",
        [Edit(2.4, 2.4, "six"), Edit(0.6, 0.9, "")],
        gen_config=steps(6),
        keep_original=False,
    )

    first, second = result.gaps
    assert first.old_start < second.old_start
    grown = sum((g.new_end - g.new_start) - (g.old_end - g.old_start) for g in result.gaps)
    assert len(result.audio) == (80 + grown) * HOP
    # Decoded from tokens: before the first gap every frame still names itself.
    levels = result.audio.reshape(-1, HOP)[: first.old_start, 0]
    assert np.allclose(levels, (200 + np.arange(first.old_start)) / 1000, atol=1e-6)


def test_a_quiet_clip_comes_back_at_its_own_level(model):
    audio = np.full(60 * HOP, 0.01, dtype=np.float32)
    result = retake(
        model,
        audio,
        "one two three",
        "one three",
        [Edit(1.0, 1.4, "")],
        gen_config=steps(4),
        keep_original=False,
    )
    # Encoded at ten times the level, decoded and turned back down.
    assert np.allclose(result.audio[: 20 * HOP], 0.01, atol=1e-6)
