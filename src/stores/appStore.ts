import { create } from "zustand";

export type EngineState =
  | "not_installed"
  | "installing"
  | "loading"
  | "ready"
  | "generating"
  | "error";

export interface AppSettings {
  outputDir: string;
  retentionDays: number;
  exportFormat: "wav" | "mp3" | "flac";
}

interface AppState {
  engineState: EngineState;
  engineProgress: number;
  engineError: string | null;
  settings: AppSettings;
  setEngineState: (state: EngineState) => void;
  setEngineProgress: (progress: number) => void;
  setEngineError: (error: string | null) => void;
  setSettings: (settings: Partial<AppSettings>) => void;
}

export const useAppStore = create<AppState>((set) => ({
  engineState: "loading",
  engineProgress: 0,
  engineError: null,
  settings: {
    outputDir: "",
    retentionDays: 30,
    exportFormat: "wav",
  },
  setEngineState: (engineState) => set({ engineState }),
  setEngineProgress: (engineProgress) => set({ engineProgress }),
  setEngineError: (engineError) => set({ engineError }),
  setSettings: (partial) =>
    set((state) => ({ settings: { ...state.settings, ...partial } })),
}));
