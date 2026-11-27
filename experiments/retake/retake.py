"""Retake: re-render a few words inside finished speech and leave the rest alone.

An experiment, not wired into the app. OmniVoice fills a grid of audio tokens
(8 codebooks x 25 frames per second) by unmasking it step by step. Its decode
loop never overwrites a cell that is already filled, and training masks random
cells, so the model has seen audio context on both sides of a gap. This module
uses that: it tokenises existing speech, cuts a gap where the words change,
and lets the model fill only the gap, with the edited transcript as text.

Nothing here has been measured yet. README.md describes the test that decides
whether this is worth building.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch
from omnivoice.models.omnivoice import (
    OmniVoiceGenerationConfig,
    _get_time_steps,
    _gumbel_sample,
    _resolve_language,
)

# A deletion still gets a short gap, so the model can smooth the join.
MIN_GAP_FRAMES = 2


@torch.inference_mode()
def infill(model, known_tokens, text, *, lang=None, gen_config=None):
    """Fill the masked cells of ``known_tokens`` so that the whole grid speaks ``text``.

    ``known_tokens`` is a (codebooks, frames) tensor of audio tokens. Cells that
    hold ``model.config.audio_mask_id`` are generated, all others are context and
    come back unchanged. Returns ``(tokens, confidence)``: the filled grid and,
    per cell, the log-probability the model gave its pick (0 for context cells).

    This is OmniVoice's ``_generate_iterative`` for a single item, with two
    changes: the target starts partly filled, and the unmasking schedule counts
    only the cells that are still masked.
    """
    gen_config = gen_config or OmniVoiceGenerationConfig()
    mask_id = model.config.audio_mask_id
    codebooks = model.config.num_audio_codebook

    tokens = known_tokens.to(model.device).long().clone().unsqueeze(0)  # [1, C, T]
    frames = tokens.shape[-1]
    confidence = torch.zeros(tokens.shape, dtype=torch.float32, device=model.device)

    # No reference audio: the speech around the gap is the voice prompt.
    inputs = model._prepare_inference_inputs(
        text, frames, None, None, lang, None, gen_config.denoise
    )
    cond_ids = inputs["input_ids"]  # [1, C, text + T], target part all MASK
    cond_len = cond_ids.shape[-1]
    cond_ids[..., cond_len - frames :] = tokens

    # Row 0 sees text and audio, row 1 (for guidance) sees the audio only.
    input_ids = torch.full(
        (2, codebooks, cond_len), mask_id, dtype=torch.long, device=model.device
    )
    audio_mask = torch.zeros((2, cond_len), dtype=torch.bool, device=model.device)
    attention = torch.zeros(
        (2, 1, cond_len, cond_len), dtype=torch.bool, device=model.device
    )
    input_ids[0] = cond_ids[0]
    audio_mask[0] = inputs["audio_mask"][0]
    attention[0] = True
    input_ids[1, :, :frames] = tokens[0]
    audio_mask[1, :frames] = True
    attention[1, :, :frames, :frames] = True
    if cond_len > frames:
        pad = torch.arange(frames, cond_len, device=model.device)
        attention[1, :, pad, pad] = True

    to_fill = int((tokens == mask_id).sum())
    timesteps = _get_time_steps(
        t_start=0.0, t_end=1.0, num_step=gen_config.num_step, t_shift=gen_config.t_shift
    ).tolist()
    schedule, remaining = [], to_fill
    for step in range(gen_config.num_step):
        if step == gen_config.num_step - 1:
            count = remaining
        else:
            share = timesteps[step + 1] - timesteps[step]
            count = min(math.ceil(to_fill * share), remaining)
        schedule.append(count)
        remaining -= count

    layer_ids = torch.arange(codebooks, device=model.device).view(1, -1, 1)
    for count in schedule:
        if count <= 0:
            continue
        logits = model(
            input_ids=input_ids, audio_mask=audio_mask, attention_mask=attention
        ).logits.to(torch.float32)
        cond_logits = logits[0:1, :, cond_len - frames : cond_len, :]
        uncond_logits = logits[1:2, :, :frames, :]
        picks, pick_confidence = model._predict_tokens_with_scoring(
            cond_logits, uncond_logits, gen_config
        )

        scores = pick_confidence - layer_ids * gen_config.layer_penalty_factor
        if gen_config.position_temperature > 0.0:
            scores = _gumbel_sample(scores, gen_config.position_temperature)
        scores.masked_fill_(tokens != mask_id, -float("inf"))

        chosen = torch.topk(scores.flatten(), count).indices
        flat_tokens, flat_confidence = tokens.flatten(), confidence.flatten()
        flat_tokens[chosen] = picks.flatten()[chosen]
        flat_confidence[chosen] = pick_confidence.flatten()[chosen]
        tokens = flat_tokens.view_as(tokens)
        confidence = flat_confidence.view_as(confidence)

        input_ids[0:1, :, cond_len - frames :] = tokens
        input_ids[1:2, :, :frames] = tokens

    return tokens[0], confidence[0]


@dataclass
class Edit:
    """One change: what is spoken between ``start`` and ``end`` (seconds) afterwards."""

    start: float
    end: float  # equal to ``start`` for an insertion
    words: str  # "" for a deletion


@dataclass
class Gap:
    """Where one edit sits, in frames: in the original clip and in the result."""

    old_start: int
    old_end: int
    new_start: int
    new_end: int


@dataclass
class Retake:
    audio: np.ndarray  # mono float32 at model.sampling_rate
    gaps: list[Gap]
    confidence: float  # mean log-probability of the model's picks inside the gaps


def plan_gaps(edits, frames, frames_per_second, frames_per_weight, weigh, margin):
    """Turn edits in seconds into gaps in frames, with room for the new words.

    The new words get as many frames as the clip itself spends on text of that
    weight, so the edit keeps the speaker's pace. ``margin`` seconds on each
    side of an edit are re-rendered too, as the sounds there lead into the old
    words.
    """
    gaps, cursor, shift = [], 0, 0
    for edit in sorted(edits, key=lambda e: e.start):
        old_start = math.floor((edit.start - margin) * frames_per_second)
        old_start = min(frames, max(cursor, old_start))
        old_end = math.ceil((edit.end + margin) * frames_per_second)
        old_end = min(frames, max(old_start, old_end))
        spoken = max(0, round((edit.end - edit.start) * frames_per_second))
        around = max(0, (old_end - old_start) - spoken)
        length = round(weigh(edit.words) * frames_per_weight) + around
        length = max(MIN_GAP_FRAMES, length)
        new_start = old_start + shift
        gaps.append(Gap(old_start, old_end, new_start, new_start + length))
        shift += length - (old_end - old_start)
        cursor = old_end
    return gaps


def splice(original, decoded, gaps, hop, fade):
    """Original samples outside the gaps, decoded samples inside, cross-faded.

    Outside a gap ``decoded`` holds the same speech as ``original`` after one
    trip through the codec, so each kept stretch fades into its codec copy over
    ``fade`` samples right before a gap and back out of it right after one.
    """
    pieces, cursor, shift = [], 0, 0

    def kept(old_from, old_to, fade_in, fade_out):
        keep = original[old_from * hop : old_to * hop].copy()
        copy = decoded[(old_from + shift) * hop : (old_to + shift) * hop]
        n = min(fade, len(keep) // 2)
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
            if fade_in:
                keep[:n] = keep[:n] * ramp + copy[:n] * (1.0 - ramp)
            if fade_out:
                keep[-n:] = keep[-n:] * ramp[::-1] + copy[-n:] * (1.0 - ramp[::-1])
        return keep

    for index, gap in enumerate(gaps):
        pieces.append(kept(cursor, gap.old_start, fade_in=index > 0, fade_out=True))
        pieces.append(decoded[gap.new_start * hop : gap.new_end * hop])
        cursor, shift = gap.old_end, gap.new_end - gap.old_end
    end = len(original) // hop
    pieces.append(kept(cursor, end, fade_in=bool(gaps), fade_out=False))
    return np.concatenate(pieces)


@torch.inference_mode()
def retake(
    model,
    audio: np.ndarray,
    text_before: str,
    text_after: str,
    edits: list[Edit],
    *,
    lang: str | None = None,
    margin: float = 0.08,
    keep_original: bool = True,
    crossfade: float = 0.02,
    gen_config=None,
) -> Retake:
    """Change the words of ``audio`` at ``edits`` so that it speaks ``text_after``.

    ``audio`` is mono at ``model.sampling_rate`` and speaks ``text_before``.

    With ``keep_original`` the samples outside the edits are the original ones
    and only the edits come from the model. Without it the whole clip is
    decoded from tokens, which sends the untouched parts through the codec.
    """
    rate = model.sampling_rate
    codec = model.audio_tokenizer
    hop = codec.config.hop_length
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    audio = audio[: len(audio) - len(audio) % hop]

    # OmniVoice lifts a quiet voice prompt to this level before encoding it.
    level = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
    gain = 0.1 / level if 0 < level < 0.1 else 1.0
    wav = torch.from_numpy(audio * gain).to(codec.device)
    tokens = codec.encode(wav[None, None, :]).audio_codes.squeeze(0)  # (C, T)
    frames = tokens.shape[-1]

    weigh = model.duration_estimator.calculate_total_weight
    gaps = plan_gaps(
        edits,
        frames,
        frames_per_second=rate / hop,
        frames_per_weight=frames / max(weigh(text_before), 1.0),
        weigh=weigh,
        margin=margin,
    )

    parts, cursor = [], 0
    for gap in gaps:
        parts.append(tokens[:, cursor : gap.old_start])
        parts.append(
            torch.full(
                (tokens.shape[0], gap.new_end - gap.new_start),
                model.config.audio_mask_id,
                dtype=tokens.dtype,
                device=tokens.device,
            )
        )
        cursor = gap.old_end
    parts.append(tokens[:, cursor:])
    known = torch.cat(parts, dim=1)

    filled, confidence = infill(
        model, known, text_after, lang=_resolve_language(lang), gen_config=gen_config
    )
    decoded = (
        codec.decode(filled.to(codec.device).unsqueeze(0))
        .audio_values[0]
        .float()
        .cpu()
        .numpy()
        .reshape(-1)
    )
    # One hop of samples per frame, whatever the codec pads or trims at the end.
    wanted = known.shape[-1] * hop
    decoded = np.pad(decoded[:wanted], (0, max(0, wanted - len(decoded)))) / gain

    inside = [confidence[:, gap.new_start : gap.new_end].flatten() for gap in gaps]
    mean_confidence = float(torch.cat(inside).mean()) if inside else 0.0

    if keep_original:
        decoded = splice(audio, decoded, gaps, hop, fade=int(crossfade * rate))
    return Retake(decoded, gaps, mean_confidence)
