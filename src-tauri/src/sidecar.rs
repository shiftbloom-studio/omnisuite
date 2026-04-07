use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::time::{timeout, Duration, interval};
use std::process::Stdio;

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

pub struct SidecarManager {
    pub status: SidecarStatus,
    pub port: Option<u16>,
    pub health: Option<HealthResponse>,
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
}

pub type SharedSidecar = Arc<Mutex<SidecarManager>>;

/// Spawn the Python sidecar process and begin health polling.
/// This function acquires and releases the lock in phases to avoid holding it
/// across await points.
pub async fn spawn(shared: &SharedSidecar) -> Result<(), String> {
    // Phase 1: start the child process
    {
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Starting;
        mgr.stderr_buffer.clear();
        mgr.health = None;
        mgr.port = None;

        // Stop any previous health poll
        if let Some(handle) = mgr.health_poll_handle.take() {
            handle.abort();
        }
    }

    // Resolve sidecar directory: in dev mode it's at ../sidecar relative to src-tauri
    let sidecar_dir = resolve_sidecar_dir();
    let server_script = sidecar_dir.join("server.py");

    if !server_script.exists() {
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Error;
        return Err(format!(
            "Sidecar script not found at: {}",
            server_script.display()
        ));
    }

    // Try python, python3, py in order
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

    // Capture stderr in a background task
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

    // Read stdout line by line looking for "PORT:" prefix, with timeout
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
                        // Ignore non-PORT lines from stdout
                    }
                    Ok(None) => {
                        return Err("Sidecar process stdout closed before PORT was announced".to_string());
                    }
                    Err(e) => {
                        return Err(format!("Error reading sidecar stdout: {e}"));
                    }
                }
            }
        })
        .await;

        match port_result {
            Ok(Ok(p)) => {
                port = p;
            }
            Ok(Err(e)) => {
                let _ = child.kill().await;
                let mut mgr = shared.lock().await;
                mgr.status = SidecarStatus::Error;
                return Err(e);
            }
            Err(_) => {
                let _ = child.kill().await;
                let mut mgr = shared.lock().await;
                mgr.status = SidecarStatus::Error;
                return Err("Sidecar timed out waiting for PORT announcement".to_string());
            }
        }
    } else {
        let _ = child.kill().await;
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Error;
        return Err("Failed to capture sidecar stdout".to_string());
    }

    // Phase 2: store child and port, start health polling
    {
        let mut mgr = shared.lock().await;
        mgr.child = Some(child);
        mgr.port = Some(port);
        mgr.status = SidecarStatus::Loading;
    }

    // Start health polling in background
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

/// Periodically poll the sidecar health endpoint.
async fn poll_health_loop(shared: SharedSidecar, port: u16) {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{port}/health");
    let mut ticker = interval(Duration::from_secs(HEALTH_POLL_INTERVAL_SECS));

    loop {
        ticker.tick().await;

        let resp = client.get(&url).send().await;
        let mut mgr = shared.lock().await;

        // If we've been stopped or errored externally, exit the loop
        if mgr.status == SidecarStatus::Stopped || mgr.status == SidecarStatus::Error {
            break;
        }

        match resp {
            Ok(r) => {
                if let Ok(health) = r.json::<HealthResponse>().await {
                    if health.status == "ready" && health.model_loaded {
                        mgr.status = SidecarStatus::Ready;
                    }
                    mgr.health = Some(health);
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
}

/// Restart the sidecar with exponential backoff.
/// Retry delays: 1s, 4s, 16s. Max 3 retries, then Error status.
pub async fn restart(shared: &SharedSidecar) -> Result<(), String> {
    shutdown(shared).await;

    let retry_count = {
        let mgr = shared.lock().await;
        mgr.retry_count
    };

    if retry_count >= MAX_RETRIES {
        let mut mgr = shared.lock().await;
        mgr.status = SidecarStatus::Error;
        return Err(format!("Max retries ({MAX_RETRIES}) exceeded"));
    }

    // Exponential backoff: 1s, 4s, 16s  (4^n where n=0,1,2 => actually 1, 4, 16)
    let delay_secs = 4u64.pow(retry_count);
    // Clamp the minimum to 1 second
    let delay_secs = delay_secs.max(1);
    tokio::time::sleep(Duration::from_secs(delay_secs)).await;

    {
        let mut mgr = shared.lock().await;
        mgr.retry_count += 1;
    }

    spawn(shared).await
}

/// Resolve the sidecar directory path.
/// In dev mode: `../sidecar` relative to the src-tauri directory.
/// We try multiple strategies to find it.
fn resolve_sidecar_dir() -> std::path::PathBuf {
    // Strategy 1: relative to current exe (works in dev mode)
    if let Ok(exe) = std::env::current_exe() {
        // exe is at src-tauri/target/debug/app.exe
        // sidecar is at sidecar/ in project root
        let project_root = exe
            .parent()  // target/debug/
            .and_then(|p| p.parent())  // target/
            .and_then(|p| p.parent())  // src-tauri/
            .and_then(|p| p.parent()); // project root
        if let Some(root) = project_root {
            let sidecar = root.join("sidecar");
            if sidecar.exists() {
                return sidecar;
            }
        }
    }

    // Strategy 2: relative to CWD
    let cwd_sidecar = std::path::PathBuf::from("../sidecar");
    if cwd_sidecar.exists() {
        return cwd_sidecar;
    }

    let cwd_sidecar2 = std::path::PathBuf::from("sidecar");
    if cwd_sidecar2.exists() {
        return cwd_sidecar2;
    }

    // Fallback
    std::path::PathBuf::from("sidecar")
}

/// Find a working Python executable.
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
