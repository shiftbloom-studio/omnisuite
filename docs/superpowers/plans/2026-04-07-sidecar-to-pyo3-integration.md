# Sidecar to PyO3 Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python FastAPI sidecar with an embedded Python interpreter via PyO3, producing a single-process Tauri application.

**Architecture:** PyO3 embeds a bundled Python 3.12 interpreter directly in the Tauri process. Rust calls Python functions in-process — no HTTP, no subprocess. Model weights download on first launch via a dedicated installer screen.

**Tech Stack:** Tauri 2, PyO3, Python 3.12 (embedded), PyTorch CPU, OmniVoice, React, Zustand, TypeScript

**Spec:** `docs/superpowers/specs/2026-04-07-sidecar-to-pyo3-integration-design.md`

---

## File Structure

### Files to create:
- `python/omnisuite_engine.py` — Simplified OmniVoice engine (no HTTP, CPU-only)
- `python/requirements-cpu.txt` — CPU-only Python dependencies
- `scripts/bundle-python.ps1` — Pre-build script to create Python bundle
- `src-tauri/src/engine.rs` — PyO3 bridge: init interpreter, call Python
- `src-tauri/src/installer.rs` — Model downloader with progress events
- `src/pages/InstallEngine.tsx` — First-launch model installer UI

### Files to modify:
- `src-tauri/Cargo.toml` — Add pyo3, drop reqwest multipart
- `src-tauri/src/lib.rs` — Replace sidecar init with engine init
- `src-tauri/src/commands.rs` — Replace HTTP calls with PyO3 calls
- `src/stores/appStore.ts` — Replace sidecar state with engine state
- `src/api/commands.ts` — Update command signatures
- `src/App.tsx` — Replace sidecar events, remove VoiceDesign route
- `src/components/layout/Sidebar.tsx` — Remove DESIGN nav item

### Files to delete:
- `sidecar/` — Entire directory (server.py, engine.py, voices.py, build.py, install.py, requirements.txt)
- `src-tauri/src/sidecar.rs` — Process management
- `src/pages/VoiceDesign.tsx` — Voice design page

---

## Task 1: Create Python Engine Module

**Files:**
- Create: `python/omnisuite_engine.py`
- Create: `python/requirements-cpu.txt`

This is the simplified OmniVoice wrapper — no FastAPI, no HTTP, CPU-only. PyO3 will import and call this module directly.

- [ ] **Step 1: Create `python/requirements-cpu.txt`**

```
torchaudio
transformers>=5.3.0
accelerate>=1.13.0
safetensors>=0.7.0
tokenizers>=0.22.0
sentencepiece>=0.2.0
soundfile>=0.13.0
pydub>=0.25.0
audioop-lts>=0.2.0
numpy>=2.0.0
huggingface_hub>=1.9.0
```

Note: `torch` is installed separately with CPU index URL, `omnivoice` with `--no-deps`. FastAPI/uvicorn/python-multipart are NOT included.

- [ ] **Step 2: Create `python/omnisuite_engine.py`**

```python
"""OmniSuite embedded engine — CPU-only OmniVoice inference for PyO3."""

import io
import logging
import tempfile

logger = logging.getLogger("omnisuite_engine")

_model = None
_model_loaded = False
_loading_progress = 0.0
_loading_error = None


def load_model(model_path: str, progress_callback=None) -> None:
    """Load OmniVoice model from a local directory."""
    global _model, _model_loaded, _loading_progress, _loading_error
    try:
        import torch
        import torchaudio  # noqa: ensure available

        logger.info("Loading OmniVoice model from %s ...", model_path)
        _loading_progress = 0.1
        if progress_callback:
            progress_callback(0.1)

        from omnivoice import OmniVoice

        _loading_progress = 0.3
        if progress_callback:
            progress_callback(0.3)

        _model = OmniVoice.from_pretrained(
            model_path,
            device_map="cpu",
            dtype=torch.float32,
        )

        _loading_progress = 0.9
        if progress_callback:
            progress_callback(0.9)

        _model_loaded = True
        _loading_progress = 1.0
        _loading_error = None
        if progress_callback:
            progress_callback(1.0)

        logger.info("Model loaded successfully (CPU)")

    except Exception as e:
        _model_loaded = False
        _loading_error = str(e)
        logger.error("Failed to load model: %s", e)
        raise


def generate(
    text: str,
    ref_audio_bytes: bytes,
    ref_text: str,
    language: str = "",
    num_steps: int = 32,
    speed: float = 1.0,
) -> bytes:
    """Generate speech. Returns WAV bytes at 24kHz."""
    import torch
    import torchaudio

    if not _model_loaded or _model is None:
        raise RuntimeError("Model not loaded")

    # OmniVoice API requires a file path for ref_audio, so write to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(ref_audio_bytes)
        tmp.flush()

        kwargs = {
            "text": text,
            "ref_audio": tmp.name,
            "ref_text": ref_text,
            "num_step": num_steps,
            "speed": speed,
        }

        audio = _model.generate(**kwargs)

    # Convert tensor to WAV bytes
    buf = io.BytesIO()
    torchaudio.save(buf, audio[0].cpu(), 24000, format="wav")
    buf.seek(0)
    return buf.read()


def unload_model() -> None:
    """Unload the model and free memory."""
    global _model, _model_loaded, _loading_progress
    _model = None
    _model_loaded = False
    _loading_progress = 0.0
    import gc
    gc.collect()


def is_loaded() -> bool:
    return _model_loaded


def get_status() -> dict:
    return {
        "loaded": _model_loaded,
        "progress": _loading_progress,
        "error": _loading_error,
    }
```

- [ ] **Step 3: Commit**

```bash
git add python/omnisuite_engine.py python/requirements-cpu.txt
git commit -m "feat: add embedded Python engine module (CPU-only, no HTTP)"
```

---

## Task 2: Add PyO3 and Update Cargo Dependencies

**Files:**
- Modify: `src-tauri/Cargo.toml`

- [ ] **Step 1: Update `src-tauri/Cargo.toml`**

Add `pyo3` dependency. Change `reqwest` to drop `multipart` feature (keep `json` for model download). Remove `tauri-plugin-shell` (no longer spawning processes).

In `[dependencies]`, make these changes:

Replace:
```toml
tauri-plugin-shell = "2"
reqwest = { version = "0.12", features = ["json", "multipart"] }
```

With:
```toml
pyo3 = { version = "0.23", features = ["auto-initialize"] }
reqwest = { version = "0.12", features = ["json", "stream"] }
```

Also remove the `tauri-plugin-shell` line from the plugins section in `[dependencies]`.

- [ ] **Step 2: Commit**

```bash
git add src-tauri/Cargo.toml
git commit -m "chore: add pyo3 dep, drop reqwest multipart and tauri-plugin-shell"
```

---

## Task 3: Create Rust Engine Module (PyO3 Bridge)

**Files:**
- Create: `src-tauri/src/engine.rs`

- [ ] **Step 1: Create `src-tauri/src/engine.rs`**

```rust
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::sync::Mutex;

/// Engine state visible to the frontend.
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EngineState {
    NotInstalled,
    Installing,
    Loading,
    Ready,
    Generating,
    Error,
}

/// Thread-safe handle to the voice engine.
pub struct VoiceEngine {
    python_lib_path: PathBuf,
    model_path: PathBuf,
    state: EngineState,
    progress: f32,
    error: Option<String>,
    initialized: bool,
}

pub type SharedEngine = Arc<Mutex<VoiceEngine>>;

impl VoiceEngine {
    pub fn new(python_lib_path: PathBuf, model_path: PathBuf) -> Self {
        Self {
            python_lib_path,
            model_path,
            state: EngineState::NotInstalled,
            progress: 0.0,
            error: None,
            initialized: false,
        }
    }

    pub fn state(&self) -> &EngineState {
        &self.state
    }

    pub fn progress(&self) -> f32 {
        self.progress
    }

    pub fn error(&self) -> Option<&str> {
        self.error.as_deref()
    }

    pub fn set_state(&mut self, state: EngineState) {
        self.state = state;
    }

    pub fn set_progress(&mut self, progress: f32) {
        self.progress = progress;
    }

    pub fn set_error(&mut self, error: Option<String>) {
        self.error = error;
    }

    pub fn model_path(&self) -> &Path {
        &self.model_path
    }

    /// Initialize the Python interpreter and set PYTHONPATH.
    /// Must be called once from the main thread before any Python calls.
    pub fn init_python(&mut self) -> Result<(), String> {
        if self.initialized {
            return Ok(());
        }

        let lib_path = self.python_lib_path.to_string_lossy().to_string();

        Python::with_gil(|py| {
            // Add our bundled site-packages to sys.path
            let sys = py.import("sys").map_err(|e| format!("Failed to import sys: {e}"))?;
            let path = sys.getattr("path").map_err(|e| format!("Failed to get sys.path: {e}"))?;
            path.call_method1("insert", (0, &lib_path))
                .map_err(|e| format!("Failed to insert into sys.path: {e}"))?;

            // Also add the directory containing omnisuite_engine.py
            let engine_dir = self.python_lib_path.parent()
                .unwrap_or(&self.python_lib_path)
                .to_string_lossy()
                .to_string();
            path.call_method1("insert", (0, &engine_dir))
                .map_err(|e| format!("Failed to insert engine dir: {e}"))?;

            Ok::<(), String>(())
        })?;

        self.initialized = true;
        Ok(())
    }

    /// Check if model files exist on disk.
    pub fn is_model_installed(&self) -> bool {
        self.model_path.exists() && self.model_path.is_dir() && {
            // Check for at least one file in the model directory
            std::fs::read_dir(&self.model_path)
                .map(|mut entries| entries.next().is_some())
                .unwrap_or(false)
        }
    }

    /// Unload the model and free memory.
    pub fn unload_model(&mut self) -> Result<(), String> {
        Python::with_gil(|py| {
            let engine = py.import("omnisuite_engine")
                .map_err(|e| format!("Failed to import omnisuite_engine: {e}"))?;
            engine.getattr("unload_model")
                .and_then(|f| f.call0())
                .map_err(|e| format!("Failed to unload model: {e}"))?;
            Ok::<(), String>(())
        })?;
        self.state = EngineState::NotInstalled;
        self.progress = 0.0;
        Ok(())
    }

    /// Load the model. Blocks the calling thread (call from spawn_blocking).
    pub fn load_model(&mut self) -> Result<(), String> {
        let model_path_str = self.model_path.to_string_lossy().to_string();

        self.state = EngineState::Loading;
        self.progress = 0.0;
        self.error = None;

        let result = Python::with_gil(|py| {
            let engine = py.import("omnisuite_engine")
                .map_err(|e| format!("Failed to import omnisuite_engine: {e}"))?;

            engine.getattr("load_model")
                .and_then(|f| f.call1((&model_path_str, py.None())))
                .map_err(|e| format!("Failed to load model: {e}"))?;

            Ok::<(), String>(())
        });

        match result {
            Ok(()) => {
                self.state = EngineState::Ready;
                self.progress = 1.0;
                Ok(())
            }
            Err(e) => {
                self.state = EngineState::Error;
                self.error = Some(e.clone());
                Err(e)
            }
        }
    }

    /// Generate speech. Blocks the calling thread (call from spawn_blocking).
    pub fn generate(
        &self,
        text: &str,
        ref_audio: &[u8],
        ref_text: &str,
        language: &str,
        num_steps: u32,
        speed: f32,
    ) -> Result<Vec<u8>, String> {
        Python::with_gil(|py| {
            let engine = py.import("omnisuite_engine")
                .map_err(|e| format!("Failed to import omnisuite_engine: {e}"))?;

            let audio_bytes = PyBytes::new(py, ref_audio);

            let result = engine.getattr("generate")
                .and_then(|f| f.call1((text, audio_bytes, ref_text, language, num_steps, speed)))
                .map_err(|e| format!("Generation failed: {e}"))?;

            // Use extract which handles PyO3 version differences
            let wav_bytes: Vec<u8> = result.extract()
                .map_err(|e| format!("Expected bytes from generate(): {e}"))?;

            Ok(wav_bytes)
        })
    }

    /// Check if model is loaded in Python.
    pub fn is_loaded(&self) -> bool {
        Python::with_gil(|py| {
            py.import("omnisuite_engine")
                .and_then(|engine| engine.getattr("is_loaded"))
                .and_then(|f| f.call0())
                .and_then(|result| result.extract::<bool>())
                .unwrap_or(false)
        })
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add src-tauri/src/engine.rs
git commit -m "feat: add PyO3 engine bridge for embedded Python inference"
```

---

## Task 4: Create Model Installer Module

**Files:**
- Create: `src-tauri/src/installer.rs`

- [ ] **Step 1: Create `src-tauri/src/installer.rs`**

```rust
use reqwest::Client;
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Emitter};
use tokio::io::AsyncWriteExt;

const HF_MODEL_REPO: &str = "k2-fsa/OmniVoice";
const HF_API_BASE: &str = "https://huggingface.co/api/models";

#[derive(Clone, serde::Serialize)]
pub struct InstallProgress {
    pub downloaded: u64,
    pub total: u64,
    pub percent: f32,
}

/// List files in a HuggingFace model repo.
async fn list_model_files(client: &Client) -> Result<Vec<(String, u64)>, String> {
    let url = format!("{HF_API_BASE}/{HF_MODEL_REPO}");
    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("Failed to fetch model info: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("HuggingFace API returned {}", resp.status()));
    }

    let info: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse model info: {e}"))?;

    let siblings = info["siblings"]
        .as_array()
        .ok_or("No files found in model repo")?;

    let mut files = Vec::new();
    for file in siblings {
        let name = file["rfilename"]
            .as_str()
            .ok_or("Missing filename")?
            .to_string();
        let size = file["size"].as_u64().unwrap_or(0);
        files.push((name, size));
    }

    Ok(files)
}

/// Download a single file from HuggingFace.
async fn download_file(
    client: &Client,
    filename: &str,
    dest: &Path,
) -> Result<u64, String> {
    let url = format!(
        "https://huggingface.co/{HF_MODEL_REPO}/resolve/main/{filename}"
    );

    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("Download failed for {filename}: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("Download returned {} for {filename}", resp.status()));
    }

    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("Failed to read {filename}: {e}"))?;

    let file_path = dest.join(filename);
    if let Some(parent) = file_path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| format!("Failed to create dir: {e}"))?;
    }

    let mut file = tokio::fs::File::create(&file_path)
        .await
        .map_err(|e| format!("Failed to create {}: {e}", file_path.display()))?;

    file.write_all(&bytes)
        .await
        .map_err(|e| format!("Failed to write {}: {e}", file_path.display()))?;

    Ok(bytes.len() as u64)
}

/// Download all model files to the given directory, emitting progress events.
pub async fn install_model(
    model_dir: &Path,
    app_handle: &AppHandle,
) -> Result<(), String> {
    let client = Client::new();

    // Create model directory
    tokio::fs::create_dir_all(model_dir)
        .await
        .map_err(|e| format!("Failed to create model dir: {e}"))?;

    // List all files in the repo
    let files = list_model_files(&client).await?;
    let total_size: u64 = files.iter().map(|(_, s)| *s).sum();
    let mut downloaded: u64 = 0;

    log::info!(
        "Downloading {} files ({:.1} MB) from {HF_MODEL_REPO}",
        files.len(),
        total_size as f64 / 1_000_000.0
    );

    for (filename, _size) in &files {
        let bytes_written = download_file(&client, filename, model_dir).await?;
        downloaded += bytes_written;

        let progress = InstallProgress {
            downloaded,
            total: total_size,
            percent: if total_size > 0 {
                downloaded as f32 / total_size as f32
            } else {
                0.0
            },
        };

        let _ = app_handle.emit("engine://install-progress", &progress);
    }

    let _ = app_handle.emit("engine://install-complete", ());
    log::info!("Model installation complete");

    Ok(())
}
```

- [ ] **Step 2: Commit**

```bash
git add src-tauri/src/installer.rs
git commit -m "feat: add model installer with HuggingFace download and progress events"
```

---

## Task 5: Rewrite `lib.rs` — Replace Sidecar with Engine

**Files:**
- Modify: `src-tauri/src/lib.rs`

- [ ] **Step 1: Rewrite `src-tauri/src/lib.rs`**

Replace the entire file contents:

```rust
mod commands;
mod engine;
mod installer;
mod storage;

use commands::DbConn;
use engine::{SharedEngine, VoiceEngine};
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex as TokioMutex;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Resolve paths for Python bundle and model storage
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."));

    let python_lib_path = exe_dir.join("python").join("lib");
    let app_data = storage::get_app_data_dir();
    let model_path = app_data.join("models").join("omnivoice");

    let engine_state: SharedEngine = Arc::new(TokioMutex::new(
        VoiceEngine::new(python_lib_path, model_path),
    ));

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup({
            let engine_for_setup = Arc::clone(&engine_state);
            move |app| {
                // Setup logging in debug mode
                if cfg!(debug_assertions) {
                    let _ = app.handle().plugin(
                        tauri_plugin_log::Builder::default()
                            .level(log::LevelFilter::Info)
                            .build(),
                    );
                }

                // Ensure app data directories exist
                let app_data = storage::get_app_data_dir();
                let dirs_to_create = [
                    app_data.clone(),
                    app_data.join("voices"),
                    app_data.join("generations"),
                    app_data.join("models"),
                ];
                for dir in &dirs_to_create {
                    if let Err(e) = std::fs::create_dir_all(dir) {
                        eprintln!("Failed to create dir {}: {e}", dir.display());
                    }
                }

                // Initialize SQLite database
                let db_path = app_data.join("omnisuite.db");
                let conn = storage::init_database(&db_path)
                    .expect("Failed to initialize database");
                let db_state: DbConn = Arc::new(std::sync::Mutex::new(conn));
                app.manage(db_state);

                // Initialize Python interpreter
                {
                    let rt = tauri::async_runtime::handle();
                    let engine = Arc::clone(&engine_for_setup);
                    rt.block_on(async move {
                        let mut eng = engine.lock().await;
                        if let Err(e) = eng.init_python() {
                            eprintln!("Python init failed: {e}");
                            eng.set_state(engine::EngineState::Error);
                            eng.set_error(Some(e));
                        } else if eng.is_model_installed() {
                            // Model exists, load it in background
                            eng.set_state(engine::EngineState::Loading);
                            drop(eng);

                            let engine_for_load = Arc::clone(&engine_for_setup);
                            let handle_for_load = app.handle().clone();
                            tauri::async_runtime::spawn(async move {
                                let mut eng = engine_for_load.lock().await;
                                match eng.load_model() {
                                    Ok(()) => {
                                        let _ = handle_for_load.emit("engine://ready", ());
                                    }
                                    Err(e) => {
                                        eprintln!("Model load failed: {e}");
                                        let _ = handle_for_load.emit("engine://error", serde_json::json!({"message": e}));
                                    }
                                }
                            });
                        } else {
                            eng.set_state(engine::EngineState::NotInstalled);
                        }
                    });
                }

                Ok(())
            }
        })
        .manage(engine_state)
        .invoke_handler(tauri::generate_handler![
            commands::get_engine_status,
            commands::is_model_installed,
            commands::install_model,
            commands::reload_engine,
            commands::generate_speech,
            commands::clone_voice_test,
            commands::save_cloned_voice,
            commands::list_voices,
            commands::delete_voice,
            commands::export_voice,
            commands::import_voice,
            commands::list_history,
            commands::delete_history_entry,
            commands::clear_history,
            commands::get_settings,
            commands::update_settings,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 2: Commit**

```bash
git add src-tauri/src/lib.rs
git commit -m "feat: replace sidecar init with PyO3 engine initialization"
```

---

## Task 6: Rewrite `commands.rs` — Use Engine Instead of HTTP

**Files:**
- Modify: `src-tauri/src/commands.rs`

- [ ] **Step 1: Rewrite `src-tauri/src/commands.rs`**

Replace the entire file. The voice management, history, and settings commands stay nearly identical. The sidecar/generation commands are rewritten to use the engine.

```rust
use crate::engine::{self, EngineState, SharedEngine};
use crate::installer;
use crate::storage::{self, AppSettings, Generation, VoiceProfile};
use chrono::Utc;
use rusqlite::Connection;
use std::sync::{Arc, Mutex};
use tauri::State;
use uuid::Uuid;

/// Alias for the SQLite connection managed as Tauri state.
pub type DbConn = Arc<Mutex<Connection>>;

// ─── Engine Commands ────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_engine_status(
    engine: State<'_, SharedEngine>,
) -> Result<serde_json::Value, String> {
    let eng = engine.lock().await;
    Ok(serde_json::json!({
        "state": serde_json::to_value(eng.state()).unwrap_or_default(),
        "progress": eng.progress(),
        "error": eng.error(),
    }))
}

#[tauri::command]
pub async fn is_model_installed(
    engine: State<'_, SharedEngine>,
) -> Result<bool, String> {
    let eng = engine.lock().await;
    Ok(eng.is_model_installed())
}

#[tauri::command]
pub async fn install_model(
    engine: State<'_, SharedEngine>,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    let model_path = {
        let mut eng = engine.lock().await;
        eng.set_state(EngineState::Installing);
        eng.set_progress(0.0);
        eng.model_path().to_path_buf()
    };

    installer::install_model(&model_path, &app_handle).await?;

    // After download, load the model
    let engine_clone = engine.inner().clone();
    tokio::task::spawn_blocking(move || {
        let rt = tokio::runtime::Handle::current();
        rt.block_on(async {
            let mut eng = engine_clone.lock().await;
            eng.load_model()
        })
    })
    .await
    .map_err(|e| format!("Load task failed: {e}"))??;

    Ok(())
}

#[tauri::command]
pub async fn reload_engine(
    engine: State<'_, SharedEngine>,
) -> Result<(), String> {
    let engine_clone = engine.inner().clone();
    tokio::task::spawn_blocking(move || {
        let rt = tokio::runtime::Handle::current();
        rt.block_on(async {
            let mut eng = engine_clone.lock().await;
            let _ = eng.unload_model();
            eng.load_model()
        })
    })
    .await
    .map_err(|e| format!("Reload task failed: {e}"))??;

    Ok(())
}

// ─── Speech Generation ───────────────────────────────────────────────────────

#[tauri::command]
pub async fn generate_speech(
    voice_id: String,
    text: String,
    language: Option<String>,
    speed: Option<f32>,
    num_steps: Option<u32>,
    engine: State<'_, SharedEngine>,
    db: State<'_, DbConn>,
) -> Result<serde_json::Value, String> {
    let app_data = storage::get_app_data_dir();
    let voices_dir = app_data.join("voices");
    let generations_dir = app_data.join("generations");
    std::fs::create_dir_all(&generations_dir)
        .map_err(|e| format!("Failed to create generations dir: {e}"))?;

    // Read voice profile
    let voice_dir = voices_dir.join(&voice_id);
    let profile = storage::read_voice_profile(&voice_dir)?;

    // Read ref.wav bytes
    let ref_wav_path = voice_dir.join("ref.wav");
    let ref_wav_bytes = std::fs::read(&ref_wav_path)
        .map_err(|e| format!("Failed to read ref.wav: {e}"))?;

    let ref_text = profile.ref_text.clone().unwrap_or_default();
    let lang = language.clone().unwrap_or_default();
    let spd = speed.unwrap_or(1.0);
    let steps = num_steps.unwrap_or(32);
    let text_for_gen = text.clone();

    // Generate via PyO3 on a blocking thread
    let engine_clone = engine.inner().clone();
    let wav_bytes = tokio::task::spawn_blocking(move || {
        let rt = tokio::runtime::Handle::current();
        rt.block_on(async {
            let eng = engine_clone.lock().await;
            eng.generate(&text_for_gen, &ref_wav_bytes, &ref_text, &lang, steps, spd)
        })
    })
    .await
    .map_err(|e| format!("Generation task failed: {e}"))??;

    // Save WAV to generations dir
    let gen_id = Uuid::new_v4().to_string();
    let filename = format!("{gen_id}.wav");
    let audio_path = generations_dir.join(&filename);
    std::fs::write(&audio_path, &wav_bytes)
        .map_err(|e| format!("Failed to save audio: {e}"))?;

    // Estimate duration from WAV size (16-bit 24kHz mono = 48000 bytes/sec)
    let duration_ms = if wav_bytes.len() > 44 {
        Some(((wav_bytes.len() - 44) as i64 * 1000) / 48000)
    } else {
        None
    };

    let generation = Generation {
        id: gen_id.clone(),
        voice_id: voice_id.clone(),
        voice_name: profile.name.clone(),
        text,
        language,
        audio_path: audio_path.to_string_lossy().to_string(),
        duration_ms,
        created_at: Utc::now().format("%Y-%m-%d %H:%M:%S").to_string(),
    };

    {
        let conn = db.lock().map_err(|e| format!("DB lock error: {e}"))?;
        storage::insert_generation(&conn, &generation)
            .map_err(|e| format!("DB insert failed: {e}"))?;
    }

    Ok(serde_json::json!({
        "id": gen_id,
        "audio_path": audio_path.to_string_lossy(),
        "duration_ms": duration_ms,
    }))
}

// ─── Voice Cloning ───────────────────────────────────────────────────────────

#[tauri::command]
pub async fn clone_voice_test(
    ref_audio: Vec<u8>,
    ref_text: String,
    text: String,
    language: Option<String>,
    engine: State<'_, SharedEngine>,
) -> Result<Vec<u8>, String> {
    let lang = language.unwrap_or_default();

    let engine_clone = engine.inner().clone();
    let wav_bytes = tokio::task::spawn_blocking(move || {
        let rt = tokio::runtime::Handle::current();
        rt.block_on(async {
            let eng = engine_clone.lock().await;
            eng.generate(&text, &ref_audio, &ref_text, &lang, 32, 1.0)
        })
    })
    .await
    .map_err(|e| format!("Clone test task failed: {e}"))??;

    Ok(wav_bytes)
}

#[tauri::command]
pub async fn save_cloned_voice(
    name: String,
    tags: Vec<String>,
    ref_audio: Vec<u8>,
    ref_text: String,
    language: String,
) -> Result<VoiceProfile, String> {
    let app_data = storage::get_app_data_dir();
    let voices_dir = app_data.join("voices");
    let voice_id = Uuid::new_v4().to_string();
    let voice_dir = voices_dir.join(&voice_id);

    std::fs::create_dir_all(&voice_dir)
        .map_err(|e| format!("Failed to create voice dir: {e}"))?;

    let ref_path = voice_dir.join("ref.wav");
    std::fs::write(&ref_path, &ref_audio)
        .map_err(|e| format!("Failed to write ref.wav: {e}"))?;

    let profile = VoiceProfile {
        version: 1,
        id: voice_id,
        name,
        voice_type: "cloned".to_string(),
        language,
        tags,
        created: Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        ref_audio: Some("ref.wav".to_string()),
        ref_text: Some(ref_text),
        design_params: None,
    };

    storage::write_voice_profile(&voice_dir, &profile)?;
    Ok(profile)
}

// ─── Voice Management ────────────────────────────────────────────────────────

#[tauri::command]
pub async fn list_voices() -> Result<Vec<VoiceProfile>, String> {
    let voices_dir = storage::get_app_data_dir().join("voices");
    storage::list_voice_profiles(&voices_dir)
}

#[tauri::command]
pub async fn delete_voice(id: String) -> Result<(), String> {
    let voice_dir = storage::get_app_data_dir().join("voices").join(&id);
    storage::delete_voice_profile(&voice_dir)
}

#[tauri::command]
pub async fn export_voice(id: String) -> Result<Vec<u8>, String> {
    let voice_dir = storage::get_app_data_dir().join("voices").join(&id);
    storage::export_voice_to_zip(&voice_dir)
}

#[tauri::command]
pub async fn import_voice(zip_bytes: Vec<u8>) -> Result<VoiceProfile, String> {
    let voices_dir = storage::get_app_data_dir().join("voices");
    storage::import_voice_from_zip(&zip_bytes, &voices_dir)
}

// ─── History ─────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn list_history(
    limit: Option<u32>,
    offset: Option<u32>,
    db: State<'_, DbConn>,
) -> Result<Vec<Generation>, String> {
    let conn = db.lock().map_err(|e| format!("DB lock error: {e}"))?;
    storage::list_generations(&conn, limit.unwrap_or(50), offset.unwrap_or(0))
        .map_err(|e| format!("DB query failed: {e}"))
}

#[tauri::command]
pub async fn delete_history_entry(
    id: String,
    db: State<'_, DbConn>,
) -> Result<(), String> {
    let conn = db.lock().map_err(|e| format!("DB lock error: {e}"))?;
    if let Some(audio_path) = storage::delete_generation(&conn, &id)
        .map_err(|e| format!("DB delete failed: {e}"))? {
        let _ = std::fs::remove_file(&audio_path);
    }
    Ok(())
}

#[tauri::command]
pub async fn clear_history(
    db: State<'_, DbConn>,
) -> Result<(), String> {
    let conn = db.lock().map_err(|e| format!("DB lock error: {e}"))?;
    let paths = storage::clear_all_generations(&conn)
        .map_err(|e| format!("DB clear failed: {e}"))?;
    for path in paths {
        let _ = std::fs::remove_file(&path);
    }
    Ok(())
}

// ─── Settings ────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_settings() -> Result<AppSettings, String> {
    let settings_path = storage::get_app_data_dir().join("settings.json");
    storage::read_settings(&settings_path)
}

#[tauri::command]
pub async fn update_settings(settings: AppSettings) -> Result<(), String> {
    let settings_path = storage::get_app_data_dir().join("settings.json");
    storage::write_settings(&settings_path, &settings)
}
```

- [ ] **Step 2: Delete `src-tauri/src/sidecar.rs`**

```bash
rm src-tauri/src/sidecar.rs
```

- [ ] **Step 3: Commit**

```bash
git add src-tauri/src/commands.rs src-tauri/src/lib.rs
git rm src-tauri/src/sidecar.rs
git commit -m "feat: rewrite commands to use PyO3 engine, remove sidecar module"
```

---

## Task 7: Update Frontend State Management

**Files:**
- Modify: `src/stores/appStore.ts`
- Modify: `src/api/commands.ts`

- [ ] **Step 1: Rewrite `src/stores/appStore.ts`**

```typescript
import { create } from "zustand";

export type EngineState =
  | "not_installed"
  | "installing"
  | "loading"
  | "ready"
  | "generating"
  | "error";

export interface AppSettings {
  outputDir: string;
  retentionDays: number;
  exportFormat: "wav" | "mp3" | "flac";
}

interface AppState {
  engineState: EngineState;
  engineProgress: number;
  engineError: string | null;
  settings: AppSettings;
  setEngineState: (state: EngineState) => void;
  setEngineProgress: (progress: number) => void;
  setEngineError: (error: string | null) => void;
  setSettings: (settings: Partial<AppSettings>) => void;
}

export const useAppStore = create<AppState>((set) => ({
  engineState: "loading",
  engineProgress: 0,
  engineError: null,
  settings: {
    outputDir: "",
    retentionDays: 30,
    exportFormat: "wav",
  },
  setEngineState: (engineState) => set({ engineState }),
  setEngineProgress: (engineProgress) => set({ engineProgress }),
  setEngineError: (engineError) => set({ engineError }),
  setSettings: (partial) =>
    set((state) => ({ settings: { ...state.settings, ...partial } })),
}));
```

- [ ] **Step 2: Rewrite `src/api/commands.ts`**

```typescript
import { invoke } from "@tauri-apps/api/core";
import type { AppSettings } from "../stores/appStore";
import type { Voice } from "../stores/voiceStore";
import type { HistoryEntry } from "../stores/historyStore";

// Engine management
export async function getEngineStatus(): Promise<{
  state: string;
  progress: number;
  error: string | null;
}> {
  return invoke("get_engine_status");
}

export async function isModelInstalled(): Promise<boolean> {
  return invoke("is_model_installed");
}

export async function installModel(): Promise<void> {
  return invoke("install_model");
}

export async function reloadEngine(): Promise<void> {
  return invoke("reload_engine");
}

// Speech generation
export async function generateSpeech(params: {
  voiceId: string;
  text: string;
  language?: string;
  speed?: number;
  numSteps?: number;
}): Promise<{ id: string; audio_path: string; duration_ms: number | null }> {
  return invoke("generate_speech", {
    voiceId: params.voiceId,
    text: params.text,
    language: params.language,
    speed: params.speed,
    numSteps: params.numSteps,
  });
}

// Voice cloning
export async function cloneVoiceTest(params: {
  refAudio: number[];
  refText: string;
  text: string;
  language?: string;
}): Promise<number[]> {
  return invoke("clone_voice_test", {
    refAudio: params.refAudio,
    refText: params.refText,
    text: params.text,
    language: params.language,
  });
}

export async function saveClonedVoice(params: {
  name: string;
  tags: string[];
  refAudio: number[];
  refText: string;
  language: string;
}): Promise<Voice> {
  return invoke("save_cloned_voice", params);
}

// Voice management
export async function listVoices(): Promise<Voice[]> {
  return invoke("list_voices");
}

export async function deleteVoice(id: string): Promise<void> {
  return invoke("delete_voice", { id });
}

export async function exportVoice(id: string): Promise<number[]> {
  return invoke("export_voice", { id });
}

export async function importVoice(zipBytes: number[]): Promise<Voice> {
  return invoke("import_voice", { zipBytes });
}

// History
export async function listHistory(): Promise<HistoryEntry[]> {
  return invoke("list_history", {});
}

export async function deleteHistoryEntry(id: string): Promise<void> {
  return invoke("delete_history_entry", { id });
}

export async function clearHistory(): Promise<void> {
  return invoke("clear_history");
}

// Settings
export async function getSettings(): Promise<AppSettings> {
  return invoke("get_settings");
}

export async function updateSettings(
  settings: Partial<AppSettings>,
): Promise<void> {
  return invoke("update_settings", { settings });
}
```

- [ ] **Step 3: Commit**

```bash
git add src/stores/appStore.ts src/api/commands.ts
git commit -m "feat: update frontend state and commands for engine integration"
```

---

## Task 8: Create InstallEngine Page

**Files:**
- Create: `src/pages/InstallEngine.tsx`

- [ ] **Step 1: Create `src/pages/InstallEngine.tsx`**

```tsx
import { useState } from "react";
import { installModel } from "../api/commands";
import { useAppStore } from "../stores/appStore";
import { Button } from "../components/ui";
import { ProgressBar } from "../components/ui/ProgressBar";
import { ErrorBanner } from "../components/ui/ErrorBanner";

export default function InstallEngine() {
  const engineState = useAppStore((s) => s.engineState);
  const engineProgress = useAppStore((s) => s.engineProgress);
  const engineError = useAppStore((s) => s.engineError);
  const setEngineState = useAppStore((s) => s.setEngineState);
  const setEngineError = useAppStore((s) => s.setEngineError);

  const [installing, setInstalling] = useState(false);

  const handleInstall = async () => {
    setInstalling(true);
    setEngineError(null);
    setEngineState("installing");
    try {
      await installModel();
      // Engine will transition to "loading" then "ready" automatically
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Installation failed.";
      setEngineError(message);
      setEngineState("error");
    } finally {
      setInstalling(false);
    }
  };

  const isInstalling = engineState === "installing" || installing;

  return (
    <div className="fixed inset-0 bg-[#0A0A0A] z-50 flex flex-col items-center justify-center gap-8 p-8">
      {/* Branding */}
      <div className="flex flex-col items-center gap-2">
        <span className="text-[#FF3D00] font-mono font-black text-[28px] tracking-[6px] uppercase">
          OmniSuite
        </span>
        <div className="w-12 h-[2px] bg-[#FF3D00]" />
      </div>

      <div className="w-full max-w-md flex flex-col items-center gap-6">
        {!isInstalling && engineState !== "error" && (
          <>
            <span className="text-[#888888] font-mono text-[12px] uppercase tracking-[3px] text-center">
              Voice Engine Not Installed
            </span>
            <p className="text-[#555555] font-mono text-[11px] text-center leading-relaxed max-w-sm">
              Download the OmniVoice model to get started. This is a one-time
              download of approximately 1-2 GB.
            </p>
            <Button onClick={handleInstall}>DOWNLOAD VOICE ENGINE</Button>
          </>
        )}

        {isInstalling && (
          <div className="w-full flex flex-col items-center gap-4">
            <span className="text-[#888888] font-mono text-[12px] uppercase tracking-[3px]">
              Downloading Model
            </span>
            <ProgressBar progress={engineProgress * 100} className="w-full" />
            <span className="text-[#555555] font-mono text-[11px] tracking-[1px]">
              {Math.round(engineProgress * 100)}%
            </span>
          </div>
        )}

        {engineState === "error" && engineError && (
          <ErrorBanner
            message={engineError}
            onRetry={handleInstall}
            className="w-full"
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/pages/InstallEngine.tsx
git commit -m "feat: add InstallEngine page for first-launch model download"
```

---

## Task 9: Rewrite `App.tsx` — Engine Events and Routing

**Files:**
- Modify: `src/App.tsx`

- [ ] **Step 1: Rewrite `src/App.tsx`**

```tsx
import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import Shell from "./components/layout/Shell";
import Synthesize from "./pages/Synthesize";
import CloneVoice from "./pages/CloneVoice";
import VoiceLibrary from "./pages/VoiceLibrary";
import Settings from "./pages/Settings";
import InstallEngine from "./pages/InstallEngine";
import { LoadingScreen } from "./components/layout/LoadingScreen";
import { useAppStore, type EngineState } from "./stores/appStore";
import { getEngineStatus } from "./api/commands";

interface InstallProgressEvent {
  downloaded: number;
  total: number;
  percent: number;
}

function App() {
  const engineState = useAppStore((s) => s.engineState);
  const engineProgress = useAppStore((s) => s.engineProgress);
  const setEngineState = useAppStore((s) => s.setEngineState);
  const setEngineProgress = useAppStore((s) => s.setEngineProgress);
  const setEngineError = useAppStore((s) => s.setEngineError);

  // Check engine status on mount
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const status = await getEngineStatus();
        setEngineState(status.state as EngineState);
        setEngineProgress(status.progress);
        if (status.error) {
          setEngineError(status.error);
        }
      } catch {
        setEngineState("error");
        setEngineError("Failed to connect to engine");
      }
    };
    checkStatus();
  }, [setEngineState, setEngineProgress, setEngineError]);

  // Listen for engine events
  useEffect(() => {
    const unlistenInstall = listen<InstallProgressEvent>(
      "engine://install-progress",
      (event) => {
        setEngineProgress(event.payload.percent);
      },
    );

    const unlistenComplete = listen("engine://install-complete", () => {
      setEngineState("loading");
      setEngineProgress(0);
    });

    const unlistenReady = listen("engine://ready", () => {
      setEngineState("ready");
      setEngineProgress(1.0);
    });

    const unlistenError = listen<{ message: string }>(
      "engine://error",
      (event) => {
        setEngineState("error");
        setEngineError(event.payload.message);
      },
    );

    return () => {
      unlistenInstall.then((fn) => fn());
      unlistenComplete.then((fn) => fn());
      unlistenReady.then((fn) => fn());
      unlistenError.then((fn) => fn());
    };
  }, [setEngineState, setEngineProgress, setEngineError]);

  // Show install screen if model not installed
  if (engineState === "not_installed" || engineState === "installing") {
    return <InstallEngine />;
  }

  // Show loading screen while model loads
  if (engineState === "loading") {
    return <LoadingScreen status="loading" progress={engineProgress} />;
  }

  // Show error screen with retry
  if (engineState === "error") {
    return (
      <LoadingScreen
        status="error"
        errorMessage={useAppStore.getState().engineError ?? "Engine failed to start"}
        onRetry={async () => {
          setEngineState("loading");
          try {
            const { reloadEngine } = await import("./api/commands");
            await reloadEngine();
          } catch {
            setEngineState("error");
          }
        }}
      />
    );
  }

  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Synthesize />} />
          <Route path="/clone" element={<CloneVoice />} />
          <Route path="/library" element={<VoiceLibrary />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}

export default App;
```

- [ ] **Step 2: Commit**

```bash
git add src/App.tsx
git commit -m "feat: rewrite App.tsx with engine events and install/loading flow"
```

---

## Task 10: Update Sidebar — Remove DESIGN Nav

**Files:**
- Modify: `src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Remove DESIGN from navItems**

In `src/components/layout/Sidebar.tsx`, change the `navItems` array from:

```typescript
const navItems = [
  { to: "/", label: "SYNTHESIZE" },
  { to: "/clone", label: "CLONE" },
  { to: "/library", label: "VOICES" },
  { to: "/design", label: "DESIGN" },
  { to: "/settings", label: "SETTINGS" },
];
```

To:

```typescript
const navItems = [
  { to: "/", label: "SYNTHESIZE" },
  { to: "/clone", label: "CLONE" },
  { to: "/library", label: "VOICES" },
  { to: "/settings", label: "SETTINGS" },
];
```

- [ ] **Step 2: Commit**

```bash
git add src/components/layout/Sidebar.tsx
git commit -m "chore: remove DESIGN nav item from sidebar"
```

---

## Task 11: Delete Sidecar and VoiceDesign Files

**Files:**
- Delete: `sidecar/` (entire directory)
- Delete: `src/pages/VoiceDesign.tsx`

- [ ] **Step 1: Delete the files**

```bash
rm -rf sidecar/
rm src/pages/VoiceDesign.tsx
```

- [ ] **Step 2: Commit**

```bash
git rm -r sidecar/
git rm src/pages/VoiceDesign.tsx
git commit -m "chore: remove sidecar directory and VoiceDesign page"
```

---

## Task 12: Create Build Script

**Files:**
- Create: `scripts/bundle-python.ps1`

- [ ] **Step 1: Create `scripts/bundle-python.ps1`**

```powershell
# bundle-python.ps1 — Download and bundle Python 3.12 + CPU deps for OmniSuite
# Run from the project root: .\scripts\bundle-python.ps1

$ErrorActionPreference = "Stop"
$PythonVersion = "3.12.8"
$PythonDir = "python"
$LibDir = "$PythonDir\lib"

Write-Host "=== OmniSuite Python Bundle Script ===" -ForegroundColor Cyan

# Clean previous bundle
if (Test-Path $PythonDir) {
    Write-Host "Cleaning previous bundle..."
    Remove-Item -Recurse -Force $PythonDir
}
New-Item -ItemType Directory -Path $LibDir -Force | Out-Null

# Download embeddable Python
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonZip = "python-embed.zip"
Write-Host "Downloading Python $PythonVersion embeddable..."
Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip
Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force
Remove-Item $PythonZip

# Copy engine module
Write-Host "Copying omnisuite_engine.py..."
Copy-Item "python/omnisuite_engine.py" "$PythonDir/omnisuite_engine.py" -ErrorAction SilentlyContinue

# Install CPU-only PyTorch
Write-Host "Installing PyTorch (CPU)..."
pip install --target=$LibDir torch torchaudio --index-url https://download.pytorch.org/whl/cpu --no-cache-dir

# Install other deps
Write-Host "Installing Python dependencies..."
pip install --target=$LibDir -r python/requirements-cpu.txt --no-cache-dir

# Install OmniVoice (no deps to avoid torch version conflict)
Write-Host "Installing OmniVoice..."
pip install --target=$LibDir omnivoice --no-deps --no-cache-dir

Write-Host "=== Bundle complete ===" -ForegroundColor Green
Write-Host "Bundle at: $PythonDir"
Get-ChildItem $PythonDir -Recurse | Measure-Object -Property Length -Sum |
    ForEach-Object { Write-Host ("Total size: {0:N0} MB" -f ($_.Sum / 1MB)) }
```

- [ ] **Step 2: Commit**

```bash
git add scripts/bundle-python.ps1
git commit -m "chore: add Python bundle build script"
```

---

## Task 13: Remove tauri-plugin-shell from Tauri Config

**Files:**
- Modify: `src-tauri/capabilities/default.json` (if exists) or `src-tauri/tauri.conf.json`

- [ ] **Step 1: Check for and update Tauri config files**

Look in `src-tauri/capabilities/` and `src-tauri/tauri.conf.json` for references to `shell` plugin. Remove any `shell:*` permissions since the plugin is no longer used.

Also check `src-tauri/Cargo.toml` to ensure `tauri-plugin-shell` is fully removed.

- [ ] **Step 2: Commit**

```bash
git add -A src-tauri/
git commit -m "chore: remove shell plugin references from Tauri config"
```

---

## Task 14: Verify Build Compiles

- [ ] **Step 1: Run cargo check**

```bash
cd src-tauri && cargo check
```

Expected: compiles without errors (PyO3 may need Python 3.12 in PATH for linking during check).

- [ ] **Step 2: Run frontend build**

```bash
npm run build
```

Expected: TypeScript compiles without errors. No references to deleted VoiceDesign or sidecar types.

- [ ] **Step 3: Fix any compilation errors**

Address any type mismatches, missing imports, or config issues found in the previous steps.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve build errors from engine integration"
```
