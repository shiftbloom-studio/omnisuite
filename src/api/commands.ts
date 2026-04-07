import { invoke } from "@tauri-apps/api/core";
import type { AppSettings } from "../stores/appStore";
import type { Voice } from "../stores/voiceStore";
import type { HistoryEntry } from "../stores/historyStore";

// Sidecar management
export async function getSidecarStatus(): Promise<string> {
  return invoke("get_sidecar_status");
}

export async function restartSidecar(): Promise<void> {
  return invoke("restart_sidecar");
}

// Speech generation
export async function generateSpeech(params: {
  text: string;
  voiceId: string;
  speed?: number;
  pitch?: number;
}): Promise<{ filePath: string; duration: number }> {
  return invoke("generate_speech", params);
}

// Voice cloning
export async function cloneVoiceTest(params: {
  audioPath: string;
  text: string;
}): Promise<{ filePath: string; duration: number }> {
  return invoke("clone_voice_test", params);
}

export async function saveClonedVoice(params: {
  audioPath: string;
  name: string;
  language: string;
  tags: string[];
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

export async function exportVoice(id: string): Promise<string> {
  return invoke("export_voice", { id });
}

export async function importVoice(filePath: string): Promise<Voice> {
  return invoke("import_voice", { filePath });
}

// History
export async function listHistory(): Promise<HistoryEntry[]> {
  return invoke("list_history");
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
): Promise<AppSettings> {
  return invoke("update_settings", { settings });
}
