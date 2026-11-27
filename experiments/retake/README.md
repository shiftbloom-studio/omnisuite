# Retake

Change a few words in finished speech and leave the rest of the recording alone.

This is an experiment. Nothing in the app uses it yet, and nobody has heard a
result so far. The test below decides whether it gets built.

## The idea

OmniVoice writes speech as a grid of audio tokens and fills that grid step by
step. Its decode loop never overwrites a cell that is already filled. So we
tokenise an existing recording, cut a gap where the words change, and let the
model fill only the gap, with the edited transcript as its text. The speech on
both sides of the gap is the voice prompt.

`retake.py` holds that: `infill` fills masked cells, `retake` plans the gaps,
runs the model and puts the new span back between the original samples.

## The test

[RealEdit](https://huggingface.co/datasets/pyp1/VoiceCraft_RealEdit) is 310
real edits (substitutions, insertions, deletions) on audiobook, YouTube and
podcast recordings. `realedit.py` runs Retake on every clip it has audio for
and reports:

- the word error rate of the edited clips against the target transcripts,
  judged by Whisper large-v3,
- the same for the untouched originals, which shows how many of the errors are
  the judge's own,
- a page (`listen.html`) with both versions of every clip, to listen for
  clicks, jumps in loudness or a change of voice at the edit.

Numbers others report on the full set: CosyEdit 4.50 %, Step-Audio-EditX
10.76 %, the original recordings 6.06 %.

How to read our result:

- Close to CosyEdit, or no worse than our own originals, and clean joins:
  build Retake into the app.
- Worse than Step-Audio-EditX, or an audible join in a third of the clips:
  fine-tune the model for filling gaps, or drop the idea.

If only part of the set can be run, compare with the originals of the same
clips, not with the published numbers.

## Running it

The manifest `RealEdit.txt` comes from the dataset page above (CC BY-NC-SA 4.0,
keep it out of the repository). The audio is not part of it. The audiobook
clips are in [LibriTTS](https://www.openslr.org/60/), the YouTube clips in
GigaSpeech, and the podcast clips need their own source. Clips without audio
are skipped and counted.

Put both under `experiments/retake/data/`, which git ignores, then:

```sh
python -m pytest experiments/retake

python experiments/retake/realedit.py \
    --manifest experiments/retake/data/RealEdit.txt \
    --audio-root experiments/retake/data/audio \
    --out experiments/retake/data/out \
    --limit 10
```

The tests need no model weights. The run needs an NVIDIA GPU to finish in
reasonable time and downloads OmniVoice, the MMS forced aligner and Whisper
large-v3 on first use. Drop `--limit` for the whole set. `--decode-all` decodes
the whole clip from tokens and keeps no original samples, which is worth a
second run to hear what the splice adds or hides.

## What it does not do yet

- The new words get as many frames as the clip spends on text of that length
  on average. A speaker who slows down or speeds up mid-sentence is not
  followed.
- Speaker similarity is not measured. The voice comes from the clip itself,
  and a score over the whole clip would mostly measure the untouched part.
- English only in the runner. The model itself is not limited to it.
