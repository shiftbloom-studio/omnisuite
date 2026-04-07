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
