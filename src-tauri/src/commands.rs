use crate::sidecar::{self, SharedSidecar};
use crate::storage::{self, AppSettings, Generation, VoiceProfile};
use chrono::Utc;
use rusqlite::Connection;
use std::sync::{Arc, Mutex};
use tauri::State;
use uuid::Uuid;

/// Alias for the SQLite connection managed as Tauri state.
/// Uses std::sync::Mutex because rusqlite::Connection is not Send.
pub type DbConn = Arc<Mutex<Connection>>;

// ─── Sidecar Commands ────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_sidecar_status(
    sidecar: State<'_, SharedSidecar>,
) -> Result<serde_json::Value, String> {
    let mgr = sidecar.lock().await;
    Ok(serde_json::json!({
        "status": mgr.get_status(),
        "health": mgr.health,
        "port": mgr.port,
    }))
}

#[tauri::command]
pub async fn restart_sidecar(
    sidecar: State<'_, SharedSidecar>,
) -> Result<(), String> {
    {
        let mut mgr = sidecar.lock().await;
        mgr.reset_retries();
    }
    sidecar::restart(&sidecar).await
}

// ─── Speech Generation ───────────────────────────────────────────────────────

#[tauri::command]
pub async fn generate_speech(
    voice_id: String,
    text: String,
    language: Option<String>,
    sidecar: State<'_, SharedSidecar>,
    db: State<'_, DbConn>,
    _app_handle: tauri::AppHandle,
) -> Result<serde_json::Value, String> {
    // Resolve app data paths
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

    // Get sidecar port
    let port = {
        let mgr = sidecar.lock().await;
        mgr.port.ok_or_else(|| "Sidecar not running".to_string())?
    };

    // Build multipart request to sidecar /generate
    let ref_part = reqwest::multipart::Part::bytes(ref_wav_bytes)
        .file_name("ref.wav")
        .mime_str("audio/wav")
        .map_err(|e| format!("Multipart error: {e}"))?;

    let mut form = reqwest::multipart::Form::new()
        .part("ref_audio", ref_part)
        .text("text", text.clone());

    if let Some(ref ref_text) = profile.ref_text {
        form = form.text("ref_text", ref_text.clone());
    }
    if let Some(ref lang) = language {
        form = form.text("language", lang.clone());
    }

    let client = reqwest::Client::new();
    let resp = client
        .post(format!("http://127.0.0.1:{port}/generate"))
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Sidecar request failed: {e}"))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Sidecar returned {status}: {body}"));
    }

    let wav_bytes = resp.bytes().await
        .map_err(|e| format!("Failed to read response bytes: {e}"))?;

    // Save WAV to generations dir
    let gen_id = Uuid::new_v4().to_string();
    let filename = format!("{gen_id}.wav");
    let audio_path = generations_dir.join(&filename);
    std::fs::write(&audio_path, &wav_bytes)
        .map_err(|e| format!("Failed to save audio: {e}"))?;

    // Estimate duration from WAV size (rough: 16-bit 24kHz mono = 48000 bytes/sec)
    let duration_ms = if wav_bytes.len() > 44 {
        Some(((wav_bytes.len() - 44) as i64 * 1000) / 48000)
    } else {
        None
    };

    let generation = Generation {
        id: gen_id.clone(),
        voice_id: voice_id.clone(),
        voice_name: profile.name.clone(),
        text: text.clone(),
        language: language.clone(),
        audio_path: audio_path.to_string_lossy().to_string(),
        duration_ms,
        created_at: Utc::now().format("%Y-%m-%d %H:%M:%S").to_string(),
    };

    // Insert into SQLite
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
    sidecar: State<'_, SharedSidecar>,
) -> Result<Vec<u8>, String> {
    let port = {
        let mgr = sidecar.lock().await;
        mgr.port.ok_or_else(|| "Sidecar not running".to_string())?
    };

    let ref_part = reqwest::multipart::Part::bytes(ref_audio)
        .file_name("ref.wav")
        .mime_str("audio/wav")
        .map_err(|e| format!("Multipart error: {e}"))?;

    let form = reqwest::multipart::Form::new()
        .part("ref_audio", ref_part)
        .text("ref_text", ref_text)
        .text("text", text);

    let client = reqwest::Client::new();
    let resp = client
        .post(format!("http://127.0.0.1:{port}/generate"))
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Sidecar request failed: {e}"))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Sidecar returned {status}: {body}"));
    }

    let wav_bytes = resp.bytes().await
        .map_err(|e| format!("Failed to read response bytes: {e}"))?;

    Ok(wav_bytes.to_vec())
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

    // Write ref.wav
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
        // Remove the audio file from disk (ignore errors if file already gone)
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
