# Enrolment round trip

Enrolment by reading shows a made-up sentence, lets the person read it aloud
and has Whisper check the words. `roundtrip.py` measures how often Whisper
gives a sentence back the way it was spelled.

It reads each sentence with OmniVoice, adds a wait before and after like a real
recording has, runs the take through `enrolment.read_take`, lets the same
Whisper that the app uses transcribe it, and judges it with
`enrolment.matches`. It also checks that no take passes for the sentence that
came before it.

A model reads here, not a person at a microphone. Real takes will do a little
worse. The run is for finding words that Whisper keeps writing another way, so
that they can leave the word lists.

```sh
python -m pytest experiments/enrolment

python experiments/enrolment/roundtrip.py \
    --enrolment path/to/enrolment.py \
    --out experiments/enrolment/data/out
```

`enrolment.py` is the module from the app. `results.csv` has one line per
sentence with what Whisper heard, `summary.json` the pass rate per language and
the words that went missing most often.

How to read the result: nearly every sentence should pass. A word that shows up
again and again under `words_missed_most` should be swapped for another one.
