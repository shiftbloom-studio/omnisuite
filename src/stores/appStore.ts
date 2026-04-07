import { create } from "zustand";

export type SidecarStatus = "starting" | "loading" | "ready" | "error" | "stopped";

export interface AppSettings {
  outputDir: string;
  retentionDays: number;
  exportFormat: "wav" | "mp3" | "flac";
}

interface AppState {
  sidecarStatus: SidecarStatus;
  sidecarProgress: number;
  settings: AppSettings;
  setSidecarStatus: (status: SidecarStatus) => void;
  setSidecarProgress: (progress: number) => void;
  setSettings: (settings: Partial<AppSettings>) => void;
}

export const useAppStore = create<AppState>((set) => ({
  sidecarStatus: "stopped",
  sidecarProgress: 0,
  settings: {
    outputDir: "",
    retentionDays: 30,
    exportFormat: "wav",
  },
  setSidecarStatus: (status) => set({ sidecarStatus: status }),
  setSidecarProgress: (progress) => set({ sidecarProgress: progress }),
  setSettings: (partial) =>
    set((state) => ({ settings: { ...state.settings, ...partial } })),
}));
