# OmniSuite Voice Application — Design Spec

## Overview

OmniSuite is a Windows desktop application for text-to-speech synthesis, voice cloning, and voice design powered by [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) — a massively multilingual zero-shot TTS model supporting 600+ languages.

The app wraps OmniVoice in a minimalistic, bold UI built with Tauri + React, targeting users who want a fast, local, GPU-accelerated voice toolkit with no cloud dependency.

## Tech Stack

| Layer | Technology |
|---|---|
| Desktop shell | Tauri v2 (Rust) |
| Frontend | React 18 + TypeScript |
| Styling | Tailwind CSS (custom brutalist theme) |
| State | Zustand |
| Backend bridge | Tauri IPC commands (Rust) |
| AI engine | Python sidecar running FastAPI + OmniVoice |
| Database | SQLite (generation history) |
| Audio | Web Audio API (playback), torchaudio (generation) |

## Architecture

```
┌─────────────────────────────────────────────┐
│  Tauri Window                               │
│  ┌───────────────────────────────────────┐  │
│  │  React Frontend (TypeScript)          │  │
│  │  Pages: Synthesize, Clone, Library,   │  │
│  │         VoiceDesign, Settings         │  │
│  └──────────────┬────────────────────────┘  │
│                 │ Tauri IPC                  │
│  ┌──────────────┴────────────────────────┐  │
│  │  Rust Backend                         │  │
│  │  - File I/O (profiles, audio, config) │  │
│  │  - Sidecar lifecycle management       │  │
│  │  - SQLite (generation history)        │  │
│  └──────────────┬────────────────────────┘  │
│                 │ HTTP (localhost)           │
│  ┌──────────────┴────────────────────────┐  │
│  │  Python Sidecar (FastAPI)             │  │
│  │  - OmniVoice model (GPU/CUDA)        │  │
│  │  - TTS generation                    │  │
│  │  - Voice cloning                     │  │
│  │  - Voice design                      │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### Communication Flow

1. **Frontend → Rust**: Tauri `invoke()` IPC for all commands
2. **Rust → Python**: HTTP requests to sidecar on `localhost:<random_port>`
3. **Rust → Filesystem**: Direct file I/O for profiles, audio, settings
4. **Rust → SQLite**: Generation history CRUD

### Sidecar Lifecycle

**States:**
1. `starting` — Sidecar process spawned, waiting for port
2. `loading` — Port received, model loading into GPU (10-60s)
3. `ready` — `/health` returns `model_loaded: true`, all features available
4. `error` — Sidecar crashed or failed to start
5. `stopped` — Graceful shutdown

**Startup sequence:**
1. Tauri spawns the Python sidecar process
2. Rust reads stdout line-by-line, looking for the `PORT:<number>` line (ignores all other output including uvicorn logs). Timeout: 30s.
3. Once port is found, Rust begins polling `/health` every 2s
4. While `model_loaded: false`, the Rust backend emits Tauri events (`sidecar://status`) containing the full health payload (`{ status, progress?, gpu_available?, ... }`). The frontend listens to this event to update the loading screen — showing download progress during `"downloading"` status and a spinner during `"loading"` status. All generate/clone/design IPC commands return an error with message "Model still loading" during this phase.
5. Once `model_loaded: true`, Rust emits a final `sidecar://ready` event. The UI transitions to the Synthesize page and all features become available.
6. A Tauri IPC command `get_sidecar_status` is also available for the frontend to poll the current state on demand (e.g., after page navigation).

**Failure handling:**
- If port is not received within 30s: state → `error`, show "Sidecar failed to start" with stderr output
- If sidecar crashes after startup: auto-restart with exponential backoff (1s, 4s, 16s), max 3 retries
- After 3 failed retries: state → `error`, show persistent error banner with last stderr output and a manual "Retry" button in Settings
- The Settings > Sidecar "Restart" button always resets the retry counter and attempts a fresh start
- Sidecar stderr is captured and stored in memory (last 100 lines) for diagnostics

**Shutdown:** Rust sends SIGTERM on app exit, waits 5s, then SIGKILL if still running.

## Project Structure

```
omnisuite/
├── src-tauri/
│   ├── src/
│   │   ├── main.rs          # App entry, sidecar boot
│   │   ├── commands.rs       # Tauri IPC command handlers
│   │   ├── sidecar.rs        # Python process lifecycle
│   │   └── storage.rs        # File I/O, SQLite, settings
│   ├── Cargo.toml
│   └── tauri.conf.json
├── src/
│   ├── App.tsx
│   ├── pages/
│   │   ├── Synthesize.tsx    # Main TTS page (home)
│   │   ├── CloneVoice.tsx    # Voice cloning workflow
│   │   ├── VoiceLibrary.tsx  # Browse/manage voices
│   │   ├── VoiceDesign.tsx   # Design voice from parameters
│   │   └── Settings.tsx      # Config, GPU status
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Shell.tsx     # App shell with sidebar
│   │   │   ├── Sidebar.tsx   # Navigation sidebar
│   │   │   └── Titlebar.tsx  # Custom window titlebar
│   │   ├── audio/
│   │   │   ├── Player.tsx    # Audio playback with waveform
│   │   │   ├── Waveform.tsx  # Waveform visualization
│   │   │   └── Recorder.tsx  # Mic recording for cloning
│   │   └── ui/
│   │       ├── Button.tsx
│   │       ├── Input.tsx
│   │       ├── Select.tsx
│   │       ├── Slider.tsx
│   │       └── Card.tsx
│   ├── stores/
│   │   ├── voiceStore.ts     # Active voice, voice list
│   │   ├── historyStore.ts   # Generation history
│   │   └── appStore.ts       # Settings, sidecar status
│   ├── api/
│   │   └── commands.ts       # Tauri invoke() wrappers for all IPC
│   └── styles/
│       └── tailwind.config.ts
├── sidecar/
│   ├── server.py             # FastAPI app, CORS, port binding
│   ├── engine.py             # OmniVoice model wrapper
│   ├── voices.py             # Default voice definitions
│   └── requirements.txt
├── package.json
├── tsconfig.json
└── LICENSE
```

## Pages & UX

### Synthesize (Home)

The primary page. Users type text and generate speech.

- **Text input**: Large textarea, monospace, supports OmniVoice non-verbal symbols like `[laughter]`
- **Voice selector**: Dropdown showing active voice name and language
- **Language selector**: Auto-detected from voice, manually overridable (600+ languages)
- **Generate button**: Triggers inference, shows progress indicator during generation
- **Audio player**: Appears after generation with waveform visualization, play/pause, scrub, time display
- **Actions**: Download as WAV, download as MP3, delete
- **History**: Scrollable list below player showing past generations (auto-saved)

### Clone Voice

Step-by-step workflow to create a cloned voice.

1. **Upload reference audio**: Drag-drop zone accepting WAV/MP3/FLAC, OR record directly via microphone
2. **Enter transcript**: Text area for the transcription of the reference audio (required by OmniVoice). This field is mandatory — the "Test" and "Save" buttons are disabled until both audio and transcript are provided. A validation message explains why the transcript is needed. Auto-transcription (e.g., via Whisper) is out of scope for v1.
3. **Name & tag**: Voice name input, optional tag chips (e.g., "female", "warm", "narrator")
4. **Test**: Generate a sample sentence with the new voice before committing
5. **Save**: Adds voice to library, immediately available in Synthesize

### Voice Library

Grid view of all voices (default + user-created).

- **Voice cards**: Name, language badge, type indicator (cloned/designed/default), mini waveform preview
- **Card actions**: Play sample, edit metadata, export as `.omnvoice`, delete
- **Import**: Button to load `.omnvoice` profile files (drag-drop supported)
- **Filters**: Search by name, filter by language, filter by type
- **Default voices section**: Visually separated, ships with 5-10 curated voices

### Voice Design

> **Feasibility note:** OmniVoice's documented API uses reference audio for voice conditioning. The speaker attribute controls (gender, age, pitch, dialect, whisper) mentioned in the model card need to be verified against the actual Python API during implementation. If OmniVoice does not expose these as independent parameters, this page will be deferred to v2 and removed from the sidebar.

Secondary voice creation method using OmniVoice's attribute controls.

- **Parameter controls**: Sliders for gender, age, pitch, dialect/accent, whisper amount
- **Live preview**: "Preview" button generates a short sample with current parameters
- **Save to Library**: When satisfied, name and save the designed voice
- **Access**: Available from Voice Library "Create Voice" menu as alternative to cloning
- **Fallback if unsupported**: If OmniVoice does not expose these controls, this page is removed entirely. Voice creation is cloning-only.

### Settings

- **Hardware**: GPU model, VRAM usage, CUDA version, inference mode (GPU/CPU), switch toggle
- **Audio**: Default export format (WAV/MP3), sample rate display (24kHz native), output directory picker
- **Storage**: Generation history retention (days), voice profiles directory, clear history
- **Sidecar**: Status indicator, model info, restart button
- **About**: App version, OmniVoice model version, links

## Voice Profile Format

Voice profiles are stored as directories in the app data folder:

```
voices/
├── sarah-k/
│   ├── profile.json
│   └── ref.wav
├── default-alex/
│   ├── profile.json
│   └── ref.wav
└── ...
```

### profile.json

```json
{
  "version": 1,
  "id": "sarah-k",
  "name": "Sarah K.",
  "type": "cloned",
  "language": "en",
  "tags": ["female", "young", "warm"],
  "created": "2026-04-07T12:00:00Z",
  "ref_audio": "ref.wav",
  "ref_text": "Transcription of the reference audio used for cloning.",
  "design_params": null
}
```

For designed voices, `ref_audio` and `ref_text` are null, and `design_params` contains:

```json
{
  "gender": "female",
  "age": 28,
  "pitch": 0.6,
  "dialect": "american",
  "whisper": 0.0
}
```

### Export Format (.omnvoice)

A `.omnvoice` file is a ZIP archive. Contents vary by voice type:

**Cloned voice:**
- `profile.json` — voice metadata
- `ref.wav` — reference audio

**Designed voice (if supported):**
- `profile.json` — voice metadata (contains `design_params`, no ref audio)

**Import validation:**
1. Extract ZIP, check for `profile.json`
2. Validate `profile.json` has required fields (`version`, `id`, `name`, `type`)
3. If `type: "cloned"`, verify `ref.wav` exists in the archive
4. If `type: "designed"`, verify `design_params` is present in JSON
5. On validation failure, show error with specific missing field/file

Portable, shareable, importable via drag-drop or file picker.

## Python Sidecar API

### Endpoints

| Endpoint | Method | Body | Response |
|---|---|---|---|
| `/health` | GET | — | `{ status, gpu_available, gpu_name, vram_total, vram_used, model_loaded }` |
| `/generate` | POST | multipart: `text`, `ref_audio` (file), `ref_text`, `language?` | WAV audio bytes (24kHz) |
| `/design/preview` | POST | `{ text, gender, age, pitch, dialect, whisper }` | WAV audio bytes (24kHz) |

The `/generate` endpoint accepts reference audio as a multipart file upload rather than a filesystem path. This eliminates the shared-path dependency between Rust and Python — the Rust backend reads the WAV from the voice profile directory and sends it as bytes. The sidecar writes it to a `tempfile.NamedTemporaryFile(delete=True)` context manager, runs inference inside the `with` block, and the temp file is cleaned up automatically on both success and exception paths (OOM, CUDA errors, malformed audio).

The `/voices/default` endpoint is removed. Default voice metadata is static and ships baked into the frontend bundle and Rust layer. No sidecar dependency needed to display the voice library.

### Engine Wrapper (engine.py)

```python
class OmniVoiceEngine:
    def __init__(self, device="cuda:0", dtype=torch.float16):
        self.model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map=device,
            dtype=dtype
        )

    def generate(self, text, ref_audio_path, ref_text, language=None):
        audio = self.model.generate(
            text=text,
            ref_audio=ref_audio_path,
            ref_text=ref_text,
        )
        return audio[0]  # tensor at 24kHz

    def design_voice(self, text, gender, age, pitch, dialect, whisper):
        # Uses OmniVoice speaker attribute controls
        ...
```

### Startup Sequence

1. FastAPI binds to `127.0.0.1:0` (OS assigns random port)
2. Prints `PORT:<number>` to stdout (uvicorn and all other logs routed to stderr via config). Note: third-party Python imports may write unexpected output to stdout before this line, so Rust must defensively scan all stdout lines for the `PORT:` prefix rather than assuming it is the first or only line.
3. `/health` returns `{ status: "downloading", progress: 0.0 }` if model weights not cached
4. Downloads model from HuggingFace Hub if needed, updating progress in `/health`
5. Loads OmniVoice model into GPU memory; `/health` returns `{ status: "loading" }`
6. Once loaded: `/health` returns `{ status: "ready", model_loaded: true, gpu_available: true, ... }`
7. Rust backend reads port from stdout (line-by-line, ignoring any non-`PORT:` lines as safety), begins health polling

## Design System

### Color Tokens

| Token | Value | Usage |
|---|---|---|
| `accent` | `#FF3D00` | Buttons, active indicators, focus states |
| `bg-base` | `#0A0A0A` | App background |
| `bg-surface` | `#0F0F0F` | Cards, panels |
| `bg-elevated` | `#141414` | Sidebar, modals |
| `border-default` | `#222222` | Standard borders |
| `border-strong` | `#333333` | Emphasized borders |
| `text-primary` | `#E0E0E0` | Primary text |
| `text-muted` | `#888888` | Secondary text (meets WCAG AA 4.5:1 on bg-base) |
| `text-accent` | `#FF3D00` | Highlighted text, labels |
| `success` | `#22C55E` | Status indicators |
| `error` | `#EF4444` | Error states |

### Typography

| Element | Font | Size | Weight | Tracking |
|---|---|---|---|---|
| Page title | JetBrains Mono | 13px | 900 | 3px, uppercase |
| Section label | JetBrains Mono | 11px | 700 | 2-3px, uppercase |
| Body text | JetBrains Mono | 14px | 400 | normal |
| Sidebar nav | JetBrains Mono | 11px | 700 | 3px, uppercase |
| Button | JetBrains Mono | 12px | 900 | 2px, uppercase |
| Monospace data | JetBrains Mono | 12px | 400 | normal |

### Spatial Rules

- **Border radius**: `0` everywhere — no exceptions
- **Border width**: 2px standard, 3px for structural dividers, 4px for active indicators
- **Padding**: 16-24px for content areas, 10-14px for interactive elements
- **Gaps**: 12-16px between elements
- **Sidebar width**: 180px
- **Active indicator**: 4px left border in accent color

### Component Patterns

- **Buttons**: Solid accent fill for primary, border-only for secondary, uppercase monospace
- **Inputs**: Dark background, 2px border, 4px left accent border on focus
- **Cards**: Surface background, 2px border, no shadow, no radius
- **Waveform**: Vertical bars in accent color (played) and muted (unplayed)
- **Progress**: Horizontal bar, accent fill on dark track

## Generation History (SQLite)

```sql
CREATE TABLE generations (
  id TEXT PRIMARY KEY,
  voice_id TEXT NOT NULL,
  voice_name TEXT NOT NULL,
  text TEXT NOT NULL,
  language TEXT,
  audio_path TEXT NOT NULL,
  duration_ms INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- `voice_name` is denormalized at write time so history entries remain readable even if the voice is later deleted.
- Auto-pruned based on retention setting (default: 30 days).
- **Pruning deletes both the DB row AND the audio file on disk.** The "Clear history" button in Settings does the same for all entries.
- When a voice is deleted from the library, its history entries remain visible (showing the denormalized `voice_name`) but marked as "(deleted voice)".

## Default Voices

Ship 5-10 curated voices covering:

| Voice | Gender | Age | Language | Style |
|---|---|---|---|---|
| Alex | Male | ~30 | English | Neutral narrator |
| Sarah | Female | ~25 | English | Warm conversational |
| Marco | Male | ~35 | English | Deep authoritative |
| Yuki | Female | ~28 | Japanese | Clear professional |
| Hans | Male | ~40 | German | Calm measured |
| Lucia | Female | ~30 | Spanish | Bright expressive |
| Pierre | Male | ~45 | French | Refined formal |
| Priya | Female | ~32 | Hindi | Friendly articulate |

Reference audio for these will be sourced from permissive-license speech datasets (LibriSpeech CC BY 4.0, Common Voice CC0/CC BY). This is a **pre-ship blocking task** — the app cannot ship without default voices. Implementation plan must include a concrete step for sourcing and testing these samples.

## Build & Distribution

### Python Sidecar Packaging

The Python sidecar is packaged as a standalone executable using **PyInstaller** (or **Nuitka** as fallback):
- Bundles Python runtime + all dependencies (torch, torchaudio, fastapi, uvicorn, omnivoice)
- Produces a single directory with an `.exe` entry point
- Configured in Tauri's `tauri.conf.json` under `bundle.externalBin`
- Total sidecar size: ~2-3GB (dominated by PyTorch + CUDA runtime)

### OmniVoice Model Weights

Model weights are **downloaded on first launch**, not bundled:
- On first start, the sidecar checks for model weights in `%APPDATA%\omnisuite\models\`
- If missing, downloads from HuggingFace Hub (estimated ~1-2GB)
- Progress is reported to the UI via the health endpoint: `{ status: "downloading", progress: 0.45 }`
- The loading screen shows download progress before transitioning to model loading
- Once downloaded, the model is cached locally and reused on subsequent launches
- Settings page shows model storage location and a "Re-download model" option
- If offline with no cached model: show clear error explaining the first-run internet requirement

### Installer

- Tauri produces an `.msi` or NSIS installer for Windows
- Installer includes the Tauri app + bundled sidecar executable
- No separate Python installation required by the user
- CUDA runtime is bundled with PyTorch inside the sidecar package
- System requirements: Windows 10+, NVIDIA GPU with CUDA support (CPU fallback available), ~4GB disk space

## Verification Plan

1. **Sidecar boot**: App launches → Python sidecar starts → health endpoint returns GPU info
2. **TTS generation**: Type text → click Generate → audio plays with waveform → saved to history
3. **Voice cloning**: Upload audio + transcript → test preview → save to library → use in Synthesize
4. **Voice export/import**: Export voice → get `.omnvoice` file → import on another instance → voice works
5. **Voice design**: Adjust sliders → preview → save → use in Synthesize
6. **History**: Generate multiple → scroll history → replay → export → delete
7. **Settings**: Toggle GPU/CPU → verify inference still works → change output directory → export lands there
