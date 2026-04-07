import { useState } from "react";
import { installModel } from "../api/commands";
import { useAppStore } from "../stores/appStore";
import { Button } from "../components/ui";
import { ProgressBar } from "../components/ui/ProgressBar";
import { ErrorBanner } from "../components/ui/ErrorBanner";

export default function InstallEngine() {
  const engineState = useAppStore((s) => s.engineState);
  const engineProgress = useAppStore((s) => s.engineProgress);
  const engineError = useAppStore((s) => s.engineError);
  const setEngineState = useAppStore((s) => s.setEngineState);
  const setEngineError = useAppStore((s) => s.setEngineError);

  const [installing, setInstalling] = useState(false);

  const handleInstall = async () => {
    setInstalling(true);
    setEngineError(null);
    setEngineState("installing");
    try {
      await installModel();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Installation failed.";
      setEngineError(message);
      setEngineState("error");
    } finally {
      setInstalling(false);
    }
  };

  const isInstalling = engineState === "installing" || installing;

  return (
    <div className="fixed inset-0 bg-[#0A0A0A] z-50 flex flex-col items-center justify-center gap-8 p-8">
      {/* Branding */}
      <div className="flex flex-col items-center gap-2">
        <span className="text-[#FF3D00] font-mono font-black text-[28px] tracking-[6px] uppercase">
          OmniSuite
        </span>
        <div className="w-12 h-[2px] bg-[#FF3D00]" />
      </div>

      <div className="w-full max-w-md flex flex-col items-center gap-6">
        {!isInstalling && engineState !== "error" && (
          <>
            <span className="text-[#888888] font-mono text-[12px] uppercase tracking-[3px] text-center">
              Voice Engine Not Installed
            </span>
            <p className="text-[#555555] font-mono text-[11px] text-center leading-relaxed max-w-sm">
              Download the OmniVoice model to get started. This is a one-time
              download of approximately 1-2 GB.
            </p>
            <Button onClick={handleInstall}>DOWNLOAD VOICE ENGINE</Button>
          </>
        )}

        {isInstalling && (
          <div className="w-full flex flex-col items-center gap-4">
            <span className="text-[#888888] font-mono text-[12px] uppercase tracking-[3px]">
              Downloading Model
            </span>
            <ProgressBar progress={engineProgress * 100} className="w-full" />
            <span className="text-[#555555] font-mono text-[11px] tracking-[1px]">
              {Math.round(engineProgress * 100)}%
            </span>
          </div>
        )}

        {engineState === "error" && engineError && (
          <ErrorBanner
            message={engineError}
            onRetry={handleInstall}
            className="w-full"
          />
        )}
      </div>
    </div>
  );
}
