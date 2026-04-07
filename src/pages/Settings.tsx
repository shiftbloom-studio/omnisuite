import { useEffect, useState } from "react";
import { Button, Badge } from "../components/ui";
import { useAppStore } from "../stores/appStore";
import {
  reloadEngine,
  getSettings,
  updateSettings,
  clearHistory,
} from "../api/commands";
import type { AppSettings } from "../stores/appStore";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-8">
      <div className="flex items-baseline gap-3 mb-4">
        <span className="text-[11px] font-bold tracking-[2px] uppercase text-[#888]">
          {title}
        </span>
        <div className="flex-1 h-[1px] bg-[#1a1a1a]" />
      </div>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[#1a1a1a]">
      <span className="text-[12px] text-[#888] tracking-[1px] uppercase">
        {label}
      </span>
      <div className="text-[13px] text-[#E0E0E0]">{children}</div>
    </div>
  );
}

export default function Settings() {
  const engineState = useAppStore((s) => s.engineState);
  const [restarting, setRestarting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [settings, setLocalSettings] = useState<AppSettings>({
    outputDir: "",
    retentionDays: 30,
    exportFormat: "wav",
  });

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const s = await getSettings();
      setLocalSettings(s);
    } catch {
      /* ignore */
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      await reloadEngine();
    } catch {
      /* ignore */
    } finally {
      setRestarting(false);
    }
  };

  const handleClearHistory = async () => {
    if (!confirm("Delete all generation history and audio files?")) return;
    setClearing(true);
    try {
      await clearHistory();
    } catch {
      /* ignore */
    } finally {
      setClearing(false);
    }
  };

  const handleRetentionChange = async (days: number) => {
    const updated: AppSettings = { ...settings, retentionDays: days };
    setLocalSettings(updated);
    try {
      await updateSettings(updated);
    } catch {
      /* ignore */
    }
  };

  const handleFormatChange = async (format: "wav" | "mp3" | "flac") => {
    const updated: AppSettings = { ...settings, exportFormat: format };
    setLocalSettings(updated);
    try {
      await updateSettings(updated);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="p-6 max-w-[700px]">
      <div className="flex items-baseline gap-3 mb-8">
        <h1 className="text-[13px] font-black tracking-[3px] uppercase text-[#FF3D00]">
          SETTINGS
        </h1>
        <div className="flex-1 h-[1px] bg-[#1a1a1a]" />
      </div>

      {/* Audio */}
      <Section title="AUDIO">
        <Row label="SAMPLE RATE">
          <span className="text-[#888]">24000 Hz (native)</span>
        </Row>
        <Row label="INFERENCE">
          <Badge variant="muted">CPU</Badge>
        </Row>
        <Row label="EXPORT FORMAT">
          <div className="flex gap-1">
            {(["wav", "mp3"] as const).map((fmt) => (
              <button
                key={fmt}
                onClick={() => handleFormatChange(fmt)}
                className="cursor-pointer bg-transparent border-0 p-0"
              >
                <Badge
                  variant={
                    settings.exportFormat === fmt ? "accent" : "muted"
                  }
                >
                  {fmt.toUpperCase()}
                </Badge>
              </button>
            ))}
          </div>
        </Row>
      </Section>

      {/* Storage */}
      <Section title="STORAGE">
        <Row label="HISTORY RETENTION">
          <div className="flex gap-1">
            {[7, 14, 30, 60, 90].map((d) => (
              <button
                key={d}
                onClick={() => handleRetentionChange(d)}
                className="cursor-pointer bg-transparent border-0 p-0"
              >
                <Badge
                  variant={
                    settings.retentionDays === d ? "accent" : "muted"
                  }
                >
                  {d}D
                </Badge>
              </button>
            ))}
          </div>
        </Row>
        <div className="pt-2">
          <Button
            variant="danger"
            size="sm"
            onClick={handleClearHistory}
            loading={clearing}
          >
            CLEAR ALL HISTORY
          </Button>
        </div>
      </Section>

      {/* Engine */}
      <Section title="ENGINE">
        <Row label="STATUS">
          <Badge
            variant={
              engineState === "ready"
                ? "success"
                : engineState === "error"
                  ? "default"
                  : "muted"
            }
          >
            {engineState.toUpperCase().replace("_", " ")}
          </Badge>
        </Row>
        <Row label="MODEL">k2-fsa/OmniVoice</Row>
        <Row label="DEVICE">CPU</Row>
        <div className="pt-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRestart}
            loading={restarting}
          >
            RELOAD ENGINE
          </Button>
        </div>
      </Section>

      {/* About */}
      <Section title="ABOUT">
        <Row label="APP">OmniSuite v0.1.0</Row>
        <Row label="ENGINE">OmniVoice (k2-fsa)</Row>
        <Row label="LICENSE">AGPL-3.0</Row>
      </Section>
    </div>
  );
}
