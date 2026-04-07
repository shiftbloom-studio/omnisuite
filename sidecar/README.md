# OmniSuite Sidecar

FastAPI server wrapping [OmniVoice](https://github.com/k2-fsa/OmniVoice) for real-time voice synthesis. Runs as a standalone background process managed by the Tauri shell.

## Prerequisites

- Python 3.10+
- CUDA-capable GPU with drivers installed
- PyTorch with CUDA support

## Development setup

```bash
cd sidecar
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

## Running in dev mode

```bash
python server.py
```

The server starts on `http://127.0.0.1:42069` by default (see `server.py` for config).

## Building the packaged executable

```bash
python build.py
```

This produces a standalone directory at `sidecar/dist/omnisuite-sidecar/` containing `omnisuite-sidecar.exe` and all required libraries.

To remove previous build artefacts without rebuilding:

```bash
python build.py --clean
```

## Expected output size

The packaged build is approximately **2 -- 3 GB** due to PyTorch and CUDA runtime libraries. The `onedir` mode is used instead of `onefile` to avoid long startup times caused by unpacking a multi-gigabyte archive on every launch.

## How Tauri uses the sidecar

The Tauri app references the sidecar via `bundle.externalBin` in `src-tauri/tauri.conf.json`. At runtime Tauri spawns `omnisuite-sidecar.exe` as a child process and communicates over HTTP.
