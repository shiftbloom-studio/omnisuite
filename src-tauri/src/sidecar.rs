use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::time::{timeout, Duration, interval};
use std::process::Stdio;
use tauri::{AppHandle, Emitter};

const STDERR_BUFFER_SIZE: usize = 100;
const HEALTH_POLL_INTERVAL_SECS: u64 = 2;
const SPAWN_TIMEOUT_SECS: u64 = 30;
const MAX_RETRIES: u32 = 3;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum SidecarStatus {
    Starting,
    Loading,
    Ready,
    Error,
    Stopped,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthResponse {
    pub status: String,
    pub model_loaded: bool,
    pub gpu_available: bool,
    pub gpu_name: Option<String>,
    pub vram_total: Option<u64>,
    pub vram_used: Option<u64>,
    pub progress: Option<f32>,
}

/// Event payload sent to the frontend via Tauri events.
#[derive(Debug, Clone, Serialize)]
pub struct SidecarEvent {
    pub status: SidecarStatus,
    pub health: Option<HealthResponse>,
    pub error: Option<String>,
}

pub struct SidecarManager {
    pub status: SidecarStatus,
    pub port: Option<u16>,
    pub health: Option<HealthResponse>,
    pub app_handle: Option<AppHandle>,
    stderr_buffer: Vec<String>,
    retry_count: u32,
    child: Option<Child>,
    health_poll_handle: Option<tokio::task::JoinHandle<()>>,
}

impl SidecarManager {
    pub fn new() -> Self {
        Self {
            status: SidecarStatus::Stopped,
            port: None,
            health: None,
            app_handle: None,
            stderr_buffer: Vec::new(),
            retry_count: 0,
            child: None,
            health_poll_handle: None,
        }
    }

    pub fn get_status(&self) -> SidecarStatus {
        self.status.clone()
    }

    pub fn get_stderr_log(&self) -> Vec<String> {
        self.stderr_buffer.clone()
    }

    fn push_stderr(&mut self, line: String) {
        if self.stderr_buffer.len() >= STDERR_BUFFER_SIZE {
            self.stderr_buffer.remove(0);
        }
        self.stderr_buffer.push(line);
    }

    pub fn reset_retries(&mut self) {
        self.retry_count = 0;
    }

    /// Emit a status event to the frontend.
    fn emit_status(&self) {
        if let Some(ref handle) = self.app_handle {
            let event = SidecarEvent {
                status: self.status.clone(),
                health: self.health.clone(),
                error: None,
            };
            let _ = handle.emit("sidecar://status", &event);
        }
    }
}

pub type SharedSidecar = Arc<Mutex<SidecarManager>>;

/// Spawn the Python sidecar process and begin health polling.
pub async fn spawn(shared: &SharedSidecar) -> Result<(), String> {
    {
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Starting;
        mgr.stderr_buffer.clear();
        mgr.health = None;
        mgr.port = None;
        mgr.emit_status();

        if let Some(handle) = mgr.health_poll_handle.take() {
            handle.abort();
        }
    }

    let sidecar_dir = resolve_sidecar_dir();
    let server_script = sidecar_dir.join("server.py");

    if !server_script.exists() {
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Error;
        mgr.emit_status();
        return Err(format!(
            "Sidecar script not found at: {}",
            server_script.display()
        ));
    }

    let python = find_python().ok_or_else(|| {
        "Python not found. Install Python 3.11+ and ensure it's in PATH.".to_string()
    })?;

    let mut child = Command::new(&python)
        .arg(&server_script)
        .current_dir(&sidecar_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("Failed to spawn sidecar ({python}): {e}"))?;

    // Capture stderr
    let stderr = child.stderr.take();
    let shared_for_stderr = Arc::clone(shared);
    if let Some(stderr) = stderr {
        tokio::spawn(async move {
            let reader = BufReader::new(stderr);
            let mut lines = reader.lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let mut mgr = shared_for_stderr.lock().await;
                mgr.push_stderr(line);
            }
        });
    }

    // Read stdout for PORT:
    let stdout = child.stdout.take();
    let port: u16;

    if let Some(stdout) = stdout {
        let reader = BufReader::new(stdout);
        let mut lines = reader.lines();

        let port_result = timeout(Duration::from_secs(SPAWN_TIMEOUT_SECS), async {
            loop {
                match lines.next_line().await {
                    Ok(Some(line)) => {
                        if let Some(port_str) = line.strip_prefix("PORT:") {
                            if let Ok(p) = port_str.trim().parse::<u16>() {
                                return Ok(p);
                            }
                        }
                    }
                    Ok(None) => {
                        return Err("Sidecar stdout closed before PORT announced".to_string());
                    }
                    Err(e) => {
                        return Err(format!("Error reading sidecar stdout: {e}"));
                    }
                }
            }
        })
        .await;

        match port_result {
            Ok(Ok(p)) => port = p,
            Ok(Err(e)) => {
                let _ = child.kill().await;
                let mut mgr = shared.lock().await;
                mgr.status = SidecarStatus::Error;
                mgr.emit_status();
                return Err(e);
            }
            Err(_) => {
                let _ = child.kill().await;
                let mut mgr = shared.lock().await;
                mgr.status = SidecarStatus::Error;
                mgr.emit_status();
                return Err("Sidecar timed out waiting for PORT".to_string());
            }
        }
    } else {
        let _ = child.kill().await;
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Error;
        mgr.emit_status();
        return Err("Failed to capture sidecar stdout".to_string());
    }

    // Store child and port
    {
        let mut mgr = shared.lock().await;
        mgr.child = Some(child);
        mgr.port = Some(port);
        mgr.status = SidecarStatus::Loading;
        mgr.emit_status();
    }

    // Start health polling
    let shared_for_health = Arc::clone(shared);
    let health_handle = tokio::spawn(async move {
        poll_health_loop(shared_for_health, port).await;
    });

    {
        let mut mgr = shared.lock().await;
        mgr.health_poll_handle = Some(health_handle);
    }

    Ok(())
}

/// Poll the sidecar health endpoint periodically and emit events.
async fn poll_health_loop(shared: SharedSidecar, port: u16) {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{port}/health");
    let mut ticker = interval(Duration::from_secs(HEALTH_POLL_INTERVAL_SECS));

    loop {
        ticker.tick().await;

        let resp = client.get(&url).send().await;
        let mut mgr = shared.lock().await;

        if mgr.status == SidecarStatus::Stopped || mgr.status == SidecarStatus::Error {
            break;
        }

        match resp {
            Ok(r) => {
                if let Ok(health) = r.json::<HealthResponse>().await {
                    let was_loading = mgr.status == SidecarStatus::Loading;
                    if health.status == "ready" && health.model_loaded {
                        mgr.status = SidecarStatus::Ready;
                    }
                    mgr.health = Some(health);
                    // Always emit so frontend gets progress updates
                    mgr.emit_status();
                    if was_loading && mgr.status == SidecarStatus::Ready {
                        // Emit a dedicated ready event
                        if let Some(ref handle) = mgr.app_handle {
                            let _ = handle.emit("sidecar://ready", ());
                        }
                    }
                }
            }
            Err(_) => {
                // Health endpoint not responding yet, keep polling
            }
        }
    }
}

/// Gracefully shut down the sidecar process.
pub async fn shutdown(shared: &SharedSidecar) {
    let mut mgr = shared.lock().await;

    if let Some(handle) = mgr.health_poll_handle.take() {
        handle.abort();
    }

    if let Some(ref mut child) = mgr.child {
        let _ = child.kill().await;
    }
    mgr.child = None;
    mgr.port = None;
    mgr.health = None;
    mgr.status = SidecarStatus::Stopped;
    mgr.emit_status();
}

/// Restart with exponential backoff.
pub async fn restart(shared: &SharedSidecar) -> Result<(), String> {
    shutdown(shared).await;

    let retry_count = {
        let mgr = shared.lock().await;
        mgr.retry_count
    };

    if retry_count >= MAX_RETRIES {
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Error;
        mgr.emit_status();
        return Err(format!("Max retries ({MAX_RETRIES}) exceeded"));
    }

    let delay_secs = 4u64.pow(retry_count).max(1);
    tokio::time::sleep(Duration::from_secs(delay_secs)).await;

    {
        let mut mgr = shared.lock().await;
        mgr.retry_count += 1;
    }

    spawn(shared).await
}

fn resolve_sidecar_dir() -> std::path::PathBuf {
    if let Ok(exe) = std::env::current_exe() {
        let project_root = exe
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
            .and_then(|p| p.parent());
        if let Some(root) = project_root {
            let sidecar = root.join("sidecar");
            if sidecar.exists() {
                return sidecar;
            }
        }
    }

    for path in &["../sidecar", "sidecar"] {
        let p = std::path::PathBuf::from(path);
        if p.exists() {
            return p;
        }
    }

    std::path::PathBuf::from("sidecar")
}

fn find_python() -> Option<String> {
    for candidate in &["python", "python3", "py"] {
        let result = std::process::Command::new(candidate)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        if let Ok(status) = result {
            if status.success() {
                return Some(candidate.to_string());
            }
        }
    }
    None
}
