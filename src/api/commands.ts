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
