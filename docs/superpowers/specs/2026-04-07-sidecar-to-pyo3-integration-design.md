# OmniSuite: Python Sidecar to PyO3 Integration

**Date:** 2026-04-07
**Status:** Draft
**Scope:** Replace the Python FastAPI sidecar with an embedded Python interpreter via PyO3, producing a single-process Tauri application that ships as a standalone Windows installer.

---

## 1. Problem Statement

OmniSuite currently runs two processes: a Tauri desktop app and a Python FastAPI sidecar. They communicate over HTTP on localhost. This introduces complexity:

- Sidecar lifecycle management (spawn, health polling, port detection, restart logic)
- HTTP serialization overhead for audio data
- Two build pipelines (Tauri + PyInstaller)
- Fragile startup handshake (stdout port announcement)
- Users may see two processes in task manager

The goal is a single process, no API layer, shipped as a single Windows installer.

---

## 2. Constraints

- **Windows-first**, single installer producing a directory-based install (exe + bundled Python + deps)
- **CPU-only** inference (no CUDA dependency)
- **Bundled Python 3.12** interpreter — no system Python requirement
- **Model downloaded separately** on first launch via in-app installer
- **Features retained:** predefined voices, voice cloning, import/export voices, generation history
- **Features dropped:** Voice Design page (`/design/preview` endpoint, `design_voice()`)
- **Minimum RAM:** 4 GB (8 GB recommended for comfortable inference)

---

## 3. Architecture

### 3.1 High-Level

```
┌─────────────────────────────────────────────┐
│              Tauri Process                   │
│                                              │
│  ┌──────────┐    invoke()    ┌────────────┐ │
│  │  React    │──────────────→│   Rust     │ │
│  │  Frontend │←──────────────│   Commands │ │
│  └──────────┘    result      └─────┬──────┘ │
│                                     │        │
│                              PyO3 calls      │
│                                     │        │
│                              ┌──────▼──────┐ │
│                              │   Python    │ │
│                              │   Engine    │ │
│                              │  (embedded) │ │
│                              └─────────────┘ │
│                                              │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐ │
│  │  SQLite  │  │  Voices/  │  │  Models/  │ │
│  │  (gens)  │  │ (profiles)│  │ (weights) │ │
│  └──────────┘  └───────────┘  └───────────┘ │
└─────────────────────────────────────────────┘
```

### 3.2 Component Breakdown

#### A. PyO3 Bridge (`src-tauri/src/engine.rs`)

Manages the embedded Python interpreter and exposes typed Rust functions.

**Embedding strategy:** PyO3 compiled against a bundled `python312.dll` shared library. At build time, `PYO3_PYTHON` points to the bundled interpreter. At runtime, `PYTHONPATH` is set to the bundled `python/lib/` directory so PyO3 finds all dependencies. No PyOxidizer — just PyO3 + a co-located Python shared library and site-packages directory.

**Responsibilities:**
- Initialize Python interpreter once at app startup
- Set `PYTHONPATH` to bundled site-packages before first import
- Import the `omnisuite_engine` Python module
- Provide `generate()` and `load_model()` functions callable from Rust
- Handle Python exceptions and convert to Rust errors
- Thread safety: all Python calls go through a single-threaded executor (Python GIL)

**Interface:**
```rust
pub struct VoiceEngine {
    // Holds Python state, initialized once
}

impl VoiceEngine {
    pub fn new() -> Result<Self>;
    pub fn is_model_installed(&self) -> bool;
    pub fn load_model(&self, model_path: &Path, progress_cb: impl Fn(f32)) -> Result<()>;
    pub fn generate(
        &self,
        text: &str,
        ref_audio: &[u8],
        ref_text: &str,
        language: &str,
        num_steps: u32,
        speed: f32,
    ) -> Result<Vec<u8>>;
    pub fn unload_model(&self) -> Result<()>;
}
```

**Threading model:** PyO3 acquires the GIL for each call. Since inference is CPU-bound and blocks the GIL, all engine calls run on a dedicated `tokio::task::spawn_blocking` thread. The Tauri async commands await these blocking tasks, keeping the UI responsive.

**GIL contention during inference:** While inference runs (potentially 5-30+ seconds on CPU for long text), the GIL is held and all other Python calls (including `get_status()`) will block. PyTorch releases the GIL for many internal C++ operations, so shorter inferences may interleave. For the UI, this means:
- Engine status cannot be polled during active generation
- The frontend should show a "Generating..." state based on the command being in-flight, not by polling
- Generation cannot be cancelled mid-inference without killing the interpreter (accepted limitation)

#### B. Python Engine Module (`python/omnisuite_engine.py`)

Simplified version of the current `sidecar/engine.py`. No HTTP framework, no server — just functions.

**Interface:**
```python
def load_model(model_path: str, progress_callback) -> None
def generate(
    text: str,
    ref_audio_bytes: bytes,
    ref_text: str,
    language: str,
    num_steps: int = 32,
    speed: float = 1.0
) -> bytes
def is_loaded() -> bool
def get_status() -> dict  # {loaded, error, progress}
```

**Key changes from current engine.py:**
- Remove all FastAPI/uvicorn imports
- Remove GPU detection (CPU-only, force `torch.device("cpu")`)
- Accept `model_path` parameter instead of downloading from HuggingFace
- Accept `ref_audio_bytes` (bytes) instead of file path; write to temp file internally if OmniVoice API requires a file path
- Return WAV bytes directly (no HTTP response wrapping)
- Remove `design_voice()` method
- Retain `num_steps` parameter (default 32)

#### C. Model Installer (`src-tauri/src/installer.rs`)

Downloads OmniVoice model weights from HuggingFace Hub on first launch.

**Responsibilities:**
- Check if model exists at `<app_data>/models/omnivoice/`
- Show estimated download size to user before starting (~1-2 GB)
- Download model files using `reqwest` with progress tracking
- Verify integrity (file size checks or checksums)
- Emit `engine://install-progress` events to frontend
- Support cancellation and retry
- Resume partial downloads if possible (HTTP range requests)

**Storage location:** `%APPDATA%/omnisuite/models/omnivoice/`

**Download source:** HuggingFace Hub API (`k2-fsa/OmniVoice`). This model is public/ungated, so no authentication token is needed. If HuggingFace rate-limits unauthenticated downloads, the installer will show a clear error with retry option.

#### D. Python Bundle

Ship a Python 3.12 environment with the app. Python 3.12 is chosen because it matches the current PyTorch CPU wheel availability for `torch` (latest stable).

**Approach:** Bundle Python shared library + site-packages alongside the exe:
- `python312.dll` — Python interpreter shared library
- `python/lib/` — All site-packages installed via `pip install --target`
- Python stdlib as zip (`python312.zip`) or extracted alongside dll
- `PYTHONPATH` set at runtime by engine.rs before first Python call

**Size estimate:** CPU-only PyTorch (~200 MB) + transformers + tokenizers + numpy + stdlib + OmniVoice ≈ **800 MB - 1.2 GB** installed size (without model). This is validated against the current sidecar's dependency footprint.

**Build integration:** Pre-build script (`scripts/bundle-python.ps1`):
1. Downloads embeddable Python 3.12 for Windows
2. `pip install --target=python/lib torch --index-url https://download.pytorch.org/whl/cpu`
3. `pip install --target=python/lib -r python/requirements-cpu.txt`
4. `pip install --target=python/lib omnivoice --no-deps`
5. Copies `python312.dll` and stdlib into bundle directory

#### E. Default Voices (`src-tauri/src/voices.rs` or `python/default_voices.json`)

The current `sidecar/voices.py` contains 8 predefined voice definitions (Alex, Sarah, Marco, etc.). These move to a bundled JSON file at `python/default_voices.json`, loaded by the Rust side at startup. Each entry has: `id`, `name`, `language`, `description`. The predefined voices reference built-in audio samples bundled with the OmniVoice model.

---

## 4. Tauri Commands (IPC Interface)

### 4.1 Commands that change

| Command | Current | New |
|---------|---------|-----|
| `get_sidecar_status` | HTTP poll to sidecar | Renamed to `get_engine_status`, direct state query |
| `restart_sidecar` | Kill + respawn process | Renamed to `reload_engine`: `engine.unload_model()` + `engine.load_model()` |
| `generate_speech` | HTTP POST to `/generate` | Direct `engine.generate()` call. Parameters: `{voice_id, text, language, speed, num_steps}` |
| `clone_voice_test` | HTTP POST to `/generate` | Direct `engine.generate()` call. Parameters: `{ref_audio: Vec<u8>, ref_text, text, language}` |

### 4.2 New commands

| Command | Purpose |
|---------|---------|
| `get_engine_status` | Returns `{state, progress, error}` — replaces `get_sidecar_status` |
| `install_model` | Triggers model download, emits `engine://install-progress` events |
| `is_model_installed` | Quick check if model files exist on disk |

### 4.3 Commands that stay the same

- `save_cloned_voice`, `list_voices`, `delete_voice`, `export_voice`, `import_voice`
- `list_history`, `delete_history_entry`, `clear_history`
- `get_settings`, `update_settings`

### 4.4 Commands removed

- `restart_sidecar` (replaced by `reload_engine`)

### 4.5 Parameter alignment

The frontend `commands.ts` and Rust command signatures will be aligned:

| Frontend function | Parameters | Notes |
|-------------------|-----------|-------|
| `generateSpeech` | `{voiceId, text, language, speed?, numSteps?}` | `pitch` removed (not used by engine), `numSteps` added |
| `cloneVoiceTest` | `{refAudio: number[], refText, text, language}` | Changed from `audioPath` to raw bytes + added `refText` |
| `getEngineStatus` | none | Replaces `getSidecarStatus` |
| `installModel` | none | New |
| `isModelInstalled` | none | New |
| `reloadEngine` | none | Replaces `restartSidecar` |

---

## 5. Frontend Changes

### 5.1 State Management

Replace `appStore.sidecarStatus` / `sidecarProgress` with:

```typescript
engineState: "not_installed" | "installing" | "loading" | "ready" | "error" | "generating"
engineProgress: number  // 0-1, used for install and model loading
engineError: string | null
```

The `"generating"` state is set locally by the command call (not by polling), since the GIL blocks status queries during inference.

### 5.2 Pages

| Page | Change |
|------|--------|
| Synthesize | Replace sidecar status display with engine status. Add `speed` and `numSteps` controls. |
| CloneVoice | Fix parameter alignment (send bytes + refText instead of audioPath) |
| VoiceLibrary | No change |
| VoiceDesign | **Remove entirely** |
| Settings | No change |
| LoadingScreen | Repurpose as model loading indicator (keep existing component) |
| **InstallEngine (new)** | First-launch screen: estimated download size, "Download Voice Engine" button, progress bar, cancel button |

### 5.3 Event System

All events use `engine://` prefix consistently:

| Event | Payload | When emitted |
|-------|---------|-------------|
| `engine://status` | `{state, progress, error}` | During model loading |
| `engine://ready` | none | Model fully loaded and ready |
| `engine://install-progress` | `{downloaded, total, percent}` | During model download |
| `engine://install-complete` | none | Model download finished |
| `engine://error` | `{message, recoverable}` | Any engine error |

### 5.4 App Flow

```
App starts
  ↓
Initialize Python interpreter (engine.rs)
  ↓
Check: is model installed?
  ├─ No  → Show InstallEngine page
  │         Display estimated download size (~1-2 GB)
  │         User clicks "Download" → install_model command
  │         Progress bar fills → engine://install-progress events
  │         On complete → auto-proceed to load
  │
  └─ Yes → Load model
            Show LoadingScreen with progress (engine://status events)
            When engine://ready → Navigate to Synthesize page
```

### 5.5 Removed components

- `VoiceDesign.tsx` page
- VoiceDesign route in router config
- VoiceDesign nav item in Sidebar

### 5.6 Storage struct changes

`VoiceProfile.design_params` field: kept in the struct for backwards compatibility with any existing voice profiles that may have it set, but ignored by the UI. No migration needed.

---

## 6. File Structure Changes

### 6.1 Files to remove

```
sidecar/                    # Entire directory
  server.py
  engine.py
  voices.py
  build.py
  install.py
  requirements.txt

src-tauri/src/sidecar.rs    # Process management
src/pages/VoiceDesign.tsx   # Voice design page
```

### 6.2 Files to add

```
python/
  omnisuite_engine.py       # Simplified engine module (PyO3 callable)
  default_voices.json       # 8 predefined voice definitions
  requirements-cpu.txt      # CPU-only dependencies

scripts/
  bundle-python.ps1         # Pre-build script to create Python bundle

src-tauri/src/engine.rs     # PyO3 bridge
src-tauri/src/installer.rs  # Model downloader
src/pages/InstallEngine.tsx # First-launch installer UI
```

### 6.3 Files to modify

```
src-tauri/src/lib.rs        # Initialize engine instead of sidecar
src-tauri/src/commands.rs   # Use engine directly instead of HTTP
src-tauri/Cargo.toml        # Add pyo3; keep reqwest (for model download, drop multipart feature)
src/stores/appStore.ts      # Replace sidecar state with engine state
src/api/commands.ts         # Update command signatures and parameter alignment
src/App.tsx                 # Replace sidecar event listeners with engine events
src/layout/Sidebar.tsx      # Remove VoiceDesign nav item
src/components/layout/LoadingScreen.tsx  # Repurpose for model loading
```

---

## 7. Build & Distribution

### 7.1 Build pipeline

1. **Pre-build** (`scripts/bundle-python.ps1`):
   - Download Python 3.12 embeddable package for Windows
   - `pip install --target=python/lib torch --index-url https://download.pytorch.org/whl/cpu`
   - `pip install --target=python/lib -r python/requirements-cpu.txt`
   - `pip install --target=python/lib omnivoice --no-deps`
   - Copy `python312.dll`, `python312.zip` (stdlib) into `python/`

2. **Cargo build:**
   - PyO3 links against bundled `python312.dll`
   - `build.rs` or env var `PYO3_PYTHON` points to bundled interpreter
   - Compile Tauri app

3. **Tauri bundle:** Package as Windows installer (.msi or NSIS .exe)
   - Include `python/` directory alongside the exe
   - Include `resources/` (frontend assets)

### 7.2 Installer output (installed directory)

```
OmniSuite/
  omnisuite.exe              # Main Tauri executable (single process)
  python312.dll              # Bundled Python 3.12 interpreter
  python312.zip              # Python stdlib
  python/
    omnisuite_engine.py      # Engine module
    default_voices.json      # Predefined voices
    lib/                     # Site-packages (torch, transformers, etc.)
  resources/                 # Frontend assets (HTML/JS/CSS)
```

### 7.3 Runtime data storage

```
%APPDATA%/omnisuite/
  models/
    omnivoice/               # Downloaded model weights (~1-2 GB)
  voices/                    # Voice profiles (unchanged)
  generations/               # Generated audio (unchanged)
  omnisuite.db               # SQLite database (unchanged)
  settings.json              # User settings (unchanged)
```

---

## 8. Error Handling

| Scenario | Handling |
|----------|----------|
| Model not installed | Show InstallEngine page |
| Download fails mid-way | Show error with "Retry" button, attempt resume via HTTP range |
| HuggingFace rate limit | Show error: "Download temporarily unavailable, try again later" |
| Model fails to load | Show error with "Retry" button, log details for debugging |
| Inference fails | Return error to frontend, show toast notification, don't crash |
| Python initialization fails | Fatal error screen with diagnostics and log path |
| Disk full during download | Detect, show message with required free space |
| Inference timeout (very long text) | No cancellation; show "Generating..." with note that long text takes time |
| Antivirus blocks exe | Document in README/installer: may need to whitelist. Future: code-sign the exe. |

---

## 9. Migration Path

This is a breaking change to the runtime architecture. No data migration needed since:
- Voice profiles are filesystem-based and unchanged
- SQLite schema is unchanged
- Settings format is unchanged
- Only the runtime architecture changes

Users upgrading from a sidecar version will need to re-download the model (now stored in `models/` subdirectory instead of being managed by the sidecar).

---

## 10. Known Limitations

- **No inference cancellation:** Once `generate()` is called, it runs to completion. The GIL prevents interruption.
- **GIL blocks status queries during generation:** Frontend must use local state ("generating") rather than polling.
- **Antivirus false positives:** Bundling Python + PyTorch in a Windows exe is a known trigger. Code signing mitigates this but is not in initial scope.
- **Model path is not user-configurable** in v1. The model is always stored at `%APPDATA%/omnisuite/models/`. Can be added later via Settings if users need it on a different drive.
- **Single-threaded inference:** Only one generation can run at a time due to GIL. Concurrent requests queue.

---

## 11. Success Criteria

- App starts as a single process (no child Python process in task manager)
- No HTTP communication — all engine calls are in-process via PyO3
- Model installs on first launch with clear progress indication and size estimate
- Voice synthesis produces identical output to the sidecar version
- Voice cloning, import/export work unchanged
- Predefined voices available without user setup
- Ships as a single Windows installer (.msi or NSIS .exe)
- Total installed size < 1.5 GB (without model weights)
