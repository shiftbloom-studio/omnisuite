use rusqlite::{Connection, Result as SqlResult, params};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{Read, Write, Cursor};
use std::path::{Path, PathBuf};
use uuid::Uuid;
use zip::write::SimpleFileOptions;

// ─── Data Structures ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Generation {
    pub id: String,
    pub voice_id: String,
    pub voice_name: String,
    pub text: String,
    pub language: Option<String>,
    pub audio_path: String,
    pub duration_ms: Option<i64>,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceProfile {
    pub version: u32,
    pub id: String,
    pub name: String,
    #[serde(rename = "type")]
    pub voice_type: String,
    pub language: String,
    pub tags: Vec<String>,
    pub created: String,
    pub ref_audio: Option<String>,
    pub ref_text: Option<String>,
    pub design_params: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppSettings {
    pub output_dir: String,
    pub retention_days: u32,
    pub export_format: String,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            output_dir: String::new(),
            retention_days: 30,
            export_format: "wav".to_string(),
        }
    }
}

// ─── App Data Directory ──────────────────────────────────────────────────────

pub fn get_app_data_dir() -> PathBuf {
    let base = dirs::data_dir().unwrap_or_else(|| PathBuf::from("."));
    base.join("omnisuite")
}

// ─── Database ────────────────────────────────────────────────────────────────

pub fn init_database(db_path: &PathBuf) -> SqlResult<Connection> {
    let conn = Connection::open(db_path)?;
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS generations (
            id TEXT PRIMARY KEY,
            voice_id TEXT NOT NULL,
            voice_name TEXT NOT NULL,
            text TEXT NOT NULL,
            language TEXT,
            audio_path TEXT NOT NULL,
            duration_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );",
    )?;
    Ok(conn)
}

pub fn insert_generation(conn: &Connection, gen: &Generation) -> SqlResult<()> {
    conn.execute(
        "INSERT INTO generations (id, voice_id, voice_name, text, language, audio_path, duration_ms, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        params![
            gen.id,
            gen.voice_id,
            gen.voice_name,
            gen.text,
            gen.language,
            gen.audio_path,
            gen.duration_ms,
            gen.created_at,
        ],
    )?;
    Ok(())
}

pub fn list_generations(conn: &Connection, limit: u32, offset: u32) -> SqlResult<Vec<Generation>> {
    let mut stmt = conn.prepare(
        "SELECT id, voice_id, voice_name, text, language, audio_path, duration_ms, created_at
         FROM generations
         ORDER BY created_at DESC
         LIMIT ?1 OFFSET ?2",
    )?;

    let rows = stmt.query_map(params![limit, offset], |row| {
        Ok(Generation {
            id: row.get(0)?,
            voice_id: row.get(1)?,
            voice_name: row.get(2)?,
            text: row.get(3)?,
            language: row.get(4)?,
            audio_path: row.get(5)?,
            duration_ms: row.get(6)?,
            created_at: row.get(7)?,
        })
    })?;

    let mut results = Vec::new();
    for row in rows {
        results.push(row?);
    }
    Ok(results)
}

/// Delete a generation row and return its audio_path so the caller can remove the file.
pub fn delete_generation(conn: &Connection, id: &str) -> SqlResult<Option<String>> {
    let audio_path: Option<String> = conn
        .query_row(
            "SELECT audio_path FROM generations WHERE id = ?1",
            params![id],
            |row| row.get(0),
        )
        .ok();

    conn.execute("DELETE FROM generations WHERE id = ?1", params![id])?;
    Ok(audio_path)
}

/// Delete rows older than `retention_days` and return their audio_paths.
pub fn prune_old_generations(conn: &Connection, retention_days: u32) -> SqlResult<Vec<String>> {
    let mut stmt = conn.prepare(
        "SELECT audio_path FROM generations
         WHERE created_at < datetime('now', ?1)",
    )?;
    let modifier = format!("-{retention_days} days");
    let paths: Vec<String> = stmt
        .query_map(params![modifier], |row| row.get(0))?
        .filter_map(|r| r.ok())
        .collect();

    conn.execute(
        "DELETE FROM generations WHERE created_at < datetime('now', ?1)",
        params![modifier],
    )?;

    Ok(paths)
}

/// Delete all generation rows and return their audio_paths.
pub fn clear_all_generations(conn: &Connection) -> SqlResult<Vec<String>> {
    let mut stmt = conn.prepare("SELECT audio_path FROM generations")?;
    let paths: Vec<String> = stmt
        .query_map([], |row| row.get(0))?
        .filter_map(|r| r.ok())
        .collect();

    conn.execute("DELETE FROM generations", [])?;
    Ok(paths)
}

// ─── Voice Profiles ──────────────────────────────────────────────────────────

/// Read profile.json from a voice directory.
pub fn read_voice_profile(dir_path: &Path) -> Result<VoiceProfile, String> {
    let profile_path = dir_path.join("profile.json");
    let data = fs::read_to_string(&profile_path)
        .map_err(|e| format!("Failed to read {}: {e}", profile_path.display()))?;
    serde_json::from_str(&data)
        .map_err(|e| format!("Failed to parse {}: {e}", profile_path.display()))
}

/// Write profile.json to a voice directory.
pub fn write_voice_profile(dir_path: &Path, profile: &VoiceProfile) -> Result<(), String> {
    fs::create_dir_all(dir_path)
        .map_err(|e| format!("Failed to create dir {}: {e}", dir_path.display()))?;

    let profile_path = dir_path.join("profile.json");
    let data = serde_json::to_string_pretty(profile)
        .map_err(|e| format!("Failed to serialize profile: {e}"))?;
    fs::write(&profile_path, data)
        .map_err(|e| format!("Failed to write {}: {e}", profile_path.display()))
}

/// Scan the voices directory and read each sub-directory's profile.json.
pub fn list_voice_profiles(voices_dir: &Path) -> Result<Vec<VoiceProfile>, String> {
    if !voices_dir.exists() {
        return Ok(vec![]);
    }

    let entries = fs::read_dir(voices_dir)
        .map_err(|e| format!("Failed to read voices dir: {e}"))?;

    let mut profiles = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|e| format!("Dir entry error: {e}"))?;
        let path = entry.path();
        if path.is_dir() {
            if let Ok(profile) = read_voice_profile(&path) {
                profiles.push(profile);
            }
        }
    }
    Ok(profiles)
}

/// Delete an entire voice directory.
pub fn delete_voice_profile(dir_path: &Path) -> Result<(), String> {
    if dir_path.exists() {
        fs::remove_dir_all(dir_path)
            .map_err(|e| format!("Failed to delete {}: {e}", dir_path.display()))?;
    }
    Ok(())
}

/// Create a .omnvoice ZIP containing profile.json and ref.wav (if present).
pub fn export_voice_to_zip(dir_path: &Path) -> Result<Vec<u8>, String> {
    let profile_path = dir_path.join("profile.json");
    let ref_wav_path = dir_path.join("ref.wav");

    let mut buf = Vec::new();
    {
        let cursor = Cursor::new(&mut buf);
        let mut zip = zip::ZipWriter::new(cursor);
        let options = SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Stored);

        // Add profile.json
        let profile_data = fs::read(&profile_path)
            .map_err(|e| format!("Failed to read profile.json: {e}"))?;
        zip.start_file("profile.json", options)
            .map_err(|e| format!("ZIP error: {e}"))?;
        zip.write_all(&profile_data)
            .map_err(|e| format!("ZIP write error: {e}"))?;

        // Add ref.wav if it exists
        if ref_wav_path.exists() {
            let wav_data = fs::read(&ref_wav_path)
                .map_err(|e| format!("Failed to read ref.wav: {e}"))?;
            zip.start_file("ref.wav", options)
                .map_err(|e| format!("ZIP error: {e}"))?;
            zip.write_all(&wav_data)
                .map_err(|e| format!("ZIP write error: {e}"))?;
        }

        zip.finish().map_err(|e| format!("ZIP finish error: {e}"))?;
    }

    Ok(buf)
}

/// Validate and extract a .omnvoice ZIP into a new voice directory.
pub fn import_voice_from_zip(zip_bytes: &[u8], voices_dir: &Path) -> Result<VoiceProfile, String> {
    let cursor = Cursor::new(zip_bytes);
    let mut archive = zip::ZipArchive::new(cursor)
        .map_err(|e| format!("Invalid ZIP: {e}"))?;

    // Validate: must contain profile.json
    let has_profile = (0..archive.len()).any(|i| {
        archive.by_index(i).map(|f| f.name() == "profile.json").unwrap_or(false)
    });
    if !has_profile {
        return Err("ZIP does not contain profile.json".to_string());
    }

    // Read profile.json from archive to get/validate the profile
    let profile: VoiceProfile = {
        let mut file = archive.by_name("profile.json")
            .map_err(|e| format!("Cannot read profile.json from ZIP: {e}"))?;
        let mut data = String::new();
        file.read_to_string(&mut data)
            .map_err(|e| format!("Failed to read profile.json: {e}"))?;
        serde_json::from_str(&data)
            .map_err(|e| format!("Invalid profile.json: {e}"))?
    };

    // Create a new directory with a fresh UUID to avoid collisions
    let new_id = Uuid::new_v4().to_string();
    let voice_dir = voices_dir.join(&new_id);
    fs::create_dir_all(&voice_dir)
        .map_err(|e| format!("Failed to create voice dir: {e}"))?;

    // Extract all files into the new directory
    for i in 0..archive.len() {
        let mut file = archive.by_index(i)
            .map_err(|e| format!("ZIP read error: {e}"))?;
        let name = file.name().to_string();

        // Only allow known filenames for safety
        if name == "profile.json" || name == "ref.wav" {
            let out_path = voice_dir.join(&name);
            let mut out_file = fs::File::create(&out_path)
                .map_err(|e| format!("Failed to create {name}: {e}"))?;
            std::io::copy(&mut file, &mut out_file)
                .map_err(|e| format!("Failed to write {name}: {e}"))?;
        }
    }

    // Update the profile with the new ID and rewrite it
    let mut imported_profile = profile;
    imported_profile.id = new_id;
    write_voice_profile(&voice_dir, &imported_profile)?;

    Ok(imported_profile)
}

// ─── Settings ────────────────────────────────────────────────────────────────

pub fn read_settings(path: &Path) -> Result<AppSettings, String> {
    if !path.exists() {
        return Ok(AppSettings::default());
    }
    let data = fs::read_to_string(path)
        .map_err(|e| format!("Failed to read settings: {e}"))?;
    serde_json::from_str(&data)
        .map_err(|e| format!("Failed to parse settings: {e}"))
}

pub fn write_settings(path: &Path, settings: &AppSettings) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create settings dir: {e}"))?;
    }
    let data = serde_json::to_string_pretty(settings)
        .map_err(|e| format!("Failed to serialize settings: {e}"))?;
    fs::write(path, data)
        .map_err(|e| format!("Failed to write settings: {e}"))
}
