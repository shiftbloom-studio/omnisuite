# OmniSuite

Local voice synthesis & cloning server, built on FastAPI + PyTorch (Apple Metal
or NVIDIA CUDA accelerated). Implements [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice).

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

## Requirements

- macOS (Apple Silicon recommended) or Linux
- Python 3.11–3.13 (installed automatically by the Homebrew formula)
- Optional: an NVIDIA GPU. It is used whenever PyTorch can see it. The Linux
  wheels from PyPI bring CUDA along. On Windows, install the CUDA build of
  PyTorch from [pytorch.org](https://pytorch.org/get-started/locally/) before
  the other requirements.

## License

[AGPL-3.0](LICENSE)
