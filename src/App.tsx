import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import Shell from "./components/layout/Shell";
import Synthesize from "./pages/Synthesize";
import CloneVoice from "./pages/CloneVoice";
import VoiceLibrary from "./pages/VoiceLibrary";
import Settings from "./pages/Settings";
import InstallEngine from "./pages/InstallEngine";
import { LoadingScreen } from "./components/layout/LoadingScreen";
import { useAppStore, type EngineState } from "./stores/appStore";
import { getEngineStatus, reloadEngine } from "./api/commands";

interface InstallProgressEvent {
  downloaded: number;
  total: number;
  percent: number;
}

function App() {
  const engineState = useAppStore((s) => s.engineState);
  const engineProgress = useAppStore((s) => s.engineProgress);
  const setEngineState = useAppStore((s) => s.setEngineState);
  const setEngineProgress = useAppStore((s) => s.setEngineProgress);
  const setEngineError = useAppStore((s) => s.setEngineError);

  // Check engine status on mount
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const status = await getEngineStatus();
        setEngineState(status.state as EngineState);
        setEngineProgress(status.progress);
        if (status.error) {
          setEngineError(status.error);
        }
      } catch {
        setEngineState("error");
        setEngineError("Failed to connect to engine");
      }
    };
    checkStatus();
  }, [setEngineState, setEngineProgress, setEngineError]);

  // Listen for engine events
  useEffect(() => {
    const unlistenInstall = listen<InstallProgressEvent>(
      "engine://install-progress",
      (event) => {
        setEngineProgress(event.payload.percent);
      },
    );

    const unlistenComplete = listen("engine://install-complete", () => {
      setEngineState("loading");
      setEngineProgress(0);
    });

    const unlistenReady = listen("engine://ready", () => {
      setEngineState("ready");
      setEngineProgress(1.0);
    });

    const unlistenError = listen<{ message: string }>(
      "engine://error",
      (event) => {
        setEngineState("error");
        setEngineError(event.payload.message);
      },
    );

    return () => {
      unlistenInstall.then((fn) => fn());
      unlistenComplete.then((fn) => fn());
      unlistenReady.then((fn) => fn());
      unlistenError.then((fn) => fn());
    };
  }, [setEngineState, setEngineProgress, setEngineError]);

  // Show install screen if model not installed
  if (engineState === "not_installed" || engineState === "installing") {
    return <InstallEngine />;
  }

  // Show loading screen while model loads
  if (engineState === "loading") {
    return <LoadingScreen status="loading" progress={engineProgress} />;
  }

  // Show error screen with retry
  if (engineState === "error") {
    return (
      <LoadingScreen
        status="error"
        errorMessage={
          useAppStore.getState().engineError ?? "Engine failed to start"
        }
        onRetry={async () => {
          setEngineState("loading");
          try {
            await reloadEngine();
          } catch {
            setEngineState("error");
          }
        }}
      />
    );
  }

  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Synthesize />} />
          <Route path="/clone" element={<CloneVoice />} />
          <Route path="/library" element={<VoiceLibrary />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}

export default App;
