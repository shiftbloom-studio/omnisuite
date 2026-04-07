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
