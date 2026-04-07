use reqwest::Client;
use std::path::Path;
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

    tokio::fs::create_dir_all(model_dir)
        .await
        .map_err(|e| format!("Failed to create model dir: {e}"))?;

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
