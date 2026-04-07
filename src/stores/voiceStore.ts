import { create } from "zustand";

export interface Voice {
  id: string;
  name: string;
  type: "default" | "cloned" | "designed";
  language: string;
  tags: string[];
  description: string;
}

interface VoiceState {
  voices: Voice[];
  activeVoice: Voice | null;
  setVoices: (voices: Voice[]) => void;
  setActiveVoice: (voice: Voice | null) => void;
  addVoice: (voice: Voice) => void;
  removeVoice: (id: string) => void;
}

export const useVoiceStore = create<VoiceState>((set) => ({
  voices: [],
  activeVoice: null,
  setVoices: (voices) => set({ voices }),
  setActiveVoice: (voice) => set({ activeVoice: voice }),
  addVoice: (voice) => set((state) => ({ voices: [...state.voices, voice] })),
  removeVoice: (id) =>
    set((state) => ({
      voices: state.voices.filter((v) => v.id !== id),
      activeVoice: state.activeVoice?.id === id ? null : state.activeVoice,
    })),
}));
