import { create } from "zustand";

export interface HistoryEntry {
  id: string;
  text: string;
  voiceId: string;
  voiceName: string;
  createdAt: string;
  duration: number;
  filePath: string;
}

interface HistoryState {
  entries: HistoryEntry[];
  setEntries: (entries: HistoryEntry[]) => void;
  addEntry: (entry: HistoryEntry) => void;
  removeEntry: (id: string) => void;
  clearEntries: () => void;
}

export const useHistoryStore = create<HistoryState>((set) => ({
  entries: [],
  setEntries: (entries) => set({ entries }),
  addEntry: (entry) =>
    set((state) => ({ entries: [entry, ...state.entries] })),
  removeEntry: (id) =>
    set((state) => ({ entries: state.entries.filter((e) => e.id !== id) })),
  clearEntries: () => set({ entries: [] }),
}));
