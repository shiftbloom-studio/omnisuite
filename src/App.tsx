import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import Shell from "./components/layout/Shell";
import Synthesize from "./pages/Synthesize";
import CloneVoice from "./pages/CloneVoice";
import VoiceLibrary from "./pages/VoiceLibrary";
import VoiceDesign from "./pages/VoiceDesign";
import Settings from "./pages/Settings";
import { useAppStore, type SidecarStatus } from "./stores/appStore";

interface SidecarEvent {
  status: string;
  health: {
    model_loaded: boolean;
    gpu_available: boolean;
    gpu_name: string | null;
    vram_total: number | null;
    vram_used: number | null;
    progress: number | null;
  } | null;
  error: string | null;
}

function App() {
  const setSidecarStatus = useAppStore((s) => s.setSidecarStatus);
  const setSidecarProgress = useAppStore((s) => s.setSidecarProgress);

  useEffect(() => {
    // Listen for sidecar status events from Rust backend
    const unlisten = listen<SidecarEvent>("sidecar://status", (event) => {
      const payload = event.payload;
      setSidecarStatus(payload.status as SidecarStatus);
      if (payload.health?.progress != null) {
        setSidecarProgress(payload.health.progress);
      }
    });

    // Also listen for the ready event
    const unlistenReady = listen("sidecar://ready", () => {
      setSidecarStatus("ready");
      setSidecarProgress(1.0);
    });

    return () => {
      unlisten.then((fn) => fn());
      unlistenReady.then((fn) => fn());
    };
  }, [setSidecarStatus, setSidecarProgress]);

  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Synthesize />} />
          <Route path="/clone" element={<CloneVoice />} />
          <Route path="/library" element={<VoiceLibrary />} />
          <Route path="/design" element={<VoiceDesign />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}

export default App;
