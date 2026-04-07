mod commands;
mod sidecar;
mod storage;

use commands::DbConn;
use sidecar::{SharedSidecar, SidecarManager};
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex as TokioMutex;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_state: SharedSidecar = Arc::new(TokioMutex::new(SidecarManager::new()));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup({
            let sidecar_for_setup = Arc::clone(&sidecar_state);
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

                // Spawn sidecar in background using Tauri's async runtime
                let sidecar_for_spawn = Arc::clone(&sidecar_for_setup);
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = sidecar::spawn(&sidecar_for_spawn).await {
                        eprintln!("Sidecar spawn failed: {e}");
                    }
                });

                Ok(())
            }
        })
        .manage(sidecar_state)
        .invoke_handler(tauri::generate_handler![
            commands::get_sidecar_status,
            commands::restart_sidecar,
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
