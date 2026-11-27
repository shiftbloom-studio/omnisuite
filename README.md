# OmniSuite

Local voice synthesis & cloning server, built on FastAPI + PyTorch (Apple Metal
accelerated). Implements [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice).

## Install

### Homebrew

```sh
brew tap shiftbloom-studio/omnisuite https://github.com/shiftbloom-studio/omnisuite
brew install omnisuite
```

The first `omnisuite` run installs Python dependencies (~300 MB) into a virtualenv.

### curl

```sh
curl -fsSL https://raw.githubusercontent.com/shiftbloom-studio/omnisuite/main/install.sh | bash
```

Installs to `~/.omnisuite` and links `omnisuite` into `~/.local/bin`. Add
`~/.local/bin` to your `PATH` if it isn't already there.

## Run

```sh
omnisuite
```

Then open <http://localhost:8000>.

## Voices

A voice is enrolled by reading. OmniSuite makes up a sentence, you read it
aloud, and Whisper checks the words on your machine. That recording becomes the
voice, with the sentence as its transcript, so there is nothing to type. A clip
taken from a video or a voice message does not contain the sentence and will
not pass. Sentences come in English and German for now.

You can still upload a clip instead. Such a voice works the same, but OmniSuite
remembers the difference, and `omnisuite verify` shows it for every file made
on your machine.

One thing this does not prove: that a person read the sentence. Another voice
model could read it too. It shows that the voice was there and spoke on
request, which a clip from somewhere else cannot do.

The first enrolment downloads Whisper, about 1.6 GB.

## Receipts

Every file OmniSuite writes is marked as AI-generated, twice:

- A signed [C2PA](https://c2pa.org) manifest inside the file. It says the audio
  came out of an AI model and carries a receipt id. Change a single sample and
  the signature no longer fits.
- An inaudible [AudioSeal](https://github.com/facebookresearch/audioseal)
  watermark in the sound itself. It is still there after the file was converted
  and the manifest got lost on the way.

A copy of each receipt stays in `data/receipts`. The text you typed never goes
into the file, and neither does the voice that spoke it.

Check any audio file:

```sh
omnisuite verify clip.wav
```

```
clip.wav: AI-generated, receipt intact
  receipt    signed by this install (OmniSuite install 3fa9c2d1)
             5d0c0b9e-7a41-4c0e-9d6b-2f1e8a3b7c55, 2026-11-27T21:03:11+00:00, k2-fsa/OmniVoice
  watermark  found, tag 3fa2, matches the receipt
  voice      enrolled by reading a sentence aloud
```

The last line is there for files made on this machine. For a voice from an
uploaded clip it reads `not enrolled, taken from an uploaded clip`.

From a checkout, run `python receipts.py verify clip.wav`. Add `--json` for
scripts. The exit code is 0 for an intact receipt, 3 when only the watermark is
left, 4 when the file changed after signing, 5 when no mark was found and 6
when the receipt is intact but signed by an install you have not trusted.
Anyone can sign a file with a key of their own, so only 0 means the file is
what a signer you know says it is.

Each install signs with its own key, made on the first start in `data/keys`.
To check files from someone else's install, ask for their `data/keys/root.pem`
and pass it along: `omnisuite verify --trust their-root.pem clip.wav`. The
`signer.key` next to it is the private part and stays on your machine.

The first start also downloads the AudioSeal weights. And a caveat that belongs
here: a watermark can be removed by someone who tries hard enough, so a file
without a mark is not proof that a person spoke it.

## Requirements

- macOS (Apple Silicon recommended) or Linux
- Python 3.11–3.13 (installed automatically by the Homebrew formula)

## License

[AGPL-3.0](LICENSE)
