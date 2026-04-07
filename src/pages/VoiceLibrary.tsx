import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Input,
  Select,
  Card,
  Badge,
  ErrorBanner,
} from "@/components/ui";
import { useVoiceStore, type Voice } from "@/stores/voiceStore";
import {
  listVoices,
  deleteVoice,
  exportVoice,
  importVoice,
} from "@/api/commands";

type TypeFilter = "all" | "default" | "cloned" | "designed";

const TYPE_FILTERS: { value: TypeFilter; label: string }[] = [
  { value: "all", label: "ALL" },
  { value: "default", label: "DEFAULT" },
  { value: "cloned", label: "CLONED" },
  { value: "designed", label: "DESIGNED" },
];

const LANGUAGE_OPTIONS = [
  { value: "", label: "All Languages" },
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
  { value: "de-DE", label: "German" },
  { value: "fr-FR", label: "French" },
  { value: "es-ES", label: "Spanish" },
  { value: "it-IT", label: "Italian" },
  { value: "ja-JP", label: "Japanese" },
  { value: "hi-IN", label: "Hindi" },
  { value: "pt-BR", label: "Portuguese (BR)" },
  { value: "zh-CN", label: "Chinese (CN)" },
  { value: "ko-KR", label: "Korean" },
];

const typeBadgeVariant = (
  type: Voice["type"],
): "default" | "accent" | "success" | "muted" => {
  switch (type) {
    case "default":
      return "muted";
    case "cloned":
      return "accent";
    case "designed":
      return "success";
    default:
      return "default";
  }
};

function VoiceLibrary() {
  const navigate = useNavigate();
  const voices = useVoiceStore((s) => s.voices);
  const setVoices = useVoiceStore((s) => s.setVoices);
  const addVoice = useVoiceStore((s) => s.addVoice);
  const removeVoice = useVoiceStore((s) => s.removeVoice);

  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [languageFilter, setLanguageFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);

  const importInputRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  // Load voices on mount
  useEffect(() => {
    (async () => {
      try {
        const data = await listVoices();
        setVoices(data);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load voices.");
      } finally {
        setLoading(false);
      }
    })();
  }, [setVoices]);

  // Filter voices
  const filtered = voices.filter((v) => {
    if (typeFilter !== "all" && v.type !== typeFilter) return false;
    if (languageFilter && v.language !== languageFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        v.name.toLowerCase().includes(q) ||
        v.tags.some((t) => t.toLowerCase().includes(q)) ||
        v.description.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const defaultVoices = filtered.filter((v) => v.type === "default");
  const userVoices = filtered.filter((v) => v.type !== "default");

  // Handlers
  const handleImportClick = () => {
    importInputRef.current?.click();
  };

  const handleImportFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setError(null);
      try {
        const voice = await importVoice(file.name);
        addVoice(voice);
      } catch (err: unknown) {
        setError(
          err instanceof Error ? err.message : "Failed to import voice.",
        );
      }
      e.target.value = "";
    },
    [addVoice],
  );

  const handleExport = useCallback(async (id: string) => {
    try {
      await exportVoice(id);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to export voice.",
      );
    }
  }, []);

  const handleDelete = useCallback(
    async (id: string) => {
      setDeletingId(id);
      setError(null);
      try {
        await deleteVoice(id);
        removeVoice(id);
        setConfirmDeleteId(null);
      } catch (err: unknown) {
        setError(
          err instanceof Error ? err.message : "Failed to delete voice.",
        );
      } finally {
        setDeletingId(null);
      }
    },
    [removeVoice],
  );

  const handlePlay = useCallback(
    (id: string) => {
      if (playingId === id) {
        audioRef.current?.pause();
        setPlayingId(null);
      } else {
        setPlayingId(id);
        // In a real implementation, we would fetch the sample audio URL from the backend
      }
    },
    [playingId],
  );

  // --- Render ---

  const renderVoiceCard = (voice: Voice) => {
    const isConfirmingDelete = confirmDeleteId === voice.id;
    const isDeleting = deletingId === voice.id;
    const isPlaying = playingId === voice.id;

    return (
      <Card
        key={voice.id}
        header={
          <div className="flex items-center justify-between gap-2">
            <span className="text-[13px] font-mono font-bold text-[#E0E0E0] truncate">
              {voice.name}
            </span>
            <Badge variant={typeBadgeVariant(voice.type)}>
              {voice.type}
            </Badge>
          </div>
        }
        footer={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => handlePlay(voice.id)}
            >
              {isPlaying ? "STOP" : "PLAY"}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => handleExport(voice.id)}
            >
              EXPORT
            </Button>
            {voice.type !== "default" && (
              <>
                {isConfirmingDelete ? (
                  <div className="flex items-center gap-1.5 ml-auto">
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => handleDelete(voice.id)}
                      loading={isDeleting}
                    >
                      CONFIRM
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setConfirmDeleteId(null)}
                      disabled={isDeleting}
                    >
                      CANCEL
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => setConfirmDeleteId(voice.id)}
                    className="ml-auto"
                  >
                    DELETE
                  </Button>
                )}
              </>
            )}
          </div>
        }
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="default">{voice.language}</Badge>
            {voice.tags.map((tag) => (
              <Badge key={tag} variant="default">
                {tag}
              </Badge>
            ))}
          </div>
          {voice.description && (
            <p className="text-[12px] font-mono text-[#888888] leading-relaxed line-clamp-2">
              {voice.description}
            </p>
          )}
        </div>
      </Card>
    );
  };

  return (
    <div>
      {/* Hidden audio element for playback */}
      <audio ref={audioRef} className="hidden" />

      {/* Hidden import input */}
      <input
        ref={importInputRef}
        type="file"
        accept=".omnvoice"
        onChange={handleImportFile}
        className="hidden"
      />

      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-[13px] font-black tracking-[3px] uppercase text-[#FF3D00]">
          VOICE LIBRARY
        </h1>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={handleImportClick}>
            IMPORT
          </Button>
          <Button size="sm" onClick={() => navigate("/clone")}>
            CLONE VOICE
          </Button>
        </div>
      </div>
      <p className="text-[11px] text-[#555555] font-mono tracking-[1px] mb-6">
        Manage default, cloned, and designed voices.
      </p>
      <hr className="border-[#1a1a1a] mb-6" />

      {/* Filters */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3 mb-6">
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="SEARCH VOICES..."
          className="flex-1"
        />
        <div className="flex items-center gap-1.5">
          {TYPE_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setTypeFilter(f.value)}
              className={[
                "px-3 py-2 text-[10px] uppercase tracking-[2px] font-mono font-bold border-2 transition-all cursor-pointer",
                typeFilter === f.value
                  ? "border-[#FF3D00] bg-[#FF3D00]/10 text-[#FF3D00]"
                  : "border-[#222222] bg-transparent text-[#888888] hover:border-[#333333]",
              ].join(" ")}
            >
              {f.label}
            </button>
          ))}
        </div>
        <Select
          value={languageFilter}
          onChange={(v) => setLanguageFilter(v)}
          options={LANGUAGE_OPTIONS}
          placeholder="Language"
          className="w-[200px]"
        />
      </div>

      {/* Error */}
      {error && (
        <ErrorBanner
          message={error}
          onDismiss={() => setError(null)}
          className="mb-6"
        />
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <span className="inline-block w-5 h-5 border-2 border-[#FF3D00] border-t-transparent animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && filtered.length === 0 && (
        <div className="flex flex-col items-center gap-3 py-16">
          <svg
            className="w-10 h-10 text-[#333333]"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
          <span className="text-[12px] text-[#555555] font-mono tracking-[1px] uppercase">
            No voices found
          </span>
          {searchQuery || typeFilter !== "all" || languageFilter ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setSearchQuery("");
                setTypeFilter("all");
                setLanguageFilter("");
              }}
            >
              CLEAR FILTERS
            </Button>
          ) : (
            <Button size="sm" onClick={() => navigate("/clone")}>
              CLONE YOUR FIRST VOICE
            </Button>
          )}
        </div>
      )}

      {/* Voice sections */}
      {!loading && filtered.length > 0 && (
        <div className="flex flex-col gap-8">
          {/* User voices */}
          {userVoices.length > 0 && (
            <section>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[10px] uppercase tracking-[3px] font-mono font-bold text-[#888888]">
                  YOUR VOICES
                </span>
                <div className="flex-1 h-[1px] bg-[#1a1a1a]" />
                <span className="text-[10px] font-mono text-[#555555]">
                  {userVoices.length}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {userVoices.map(renderVoiceCard)}
              </div>
            </section>
          )}

          {/* Default voices */}
          {defaultVoices.length > 0 && (
            <section>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[10px] uppercase tracking-[3px] font-mono font-bold text-[#888888]">
                  DEFAULT VOICES
                </span>
                <div className="flex-1 h-[1px] bg-[#1a1a1a]" />
                <span className="text-[10px] font-mono text-[#555555]">
                  {defaultVoices.length}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {defaultVoices.map(renderVoiceCard)}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export default VoiceLibrary;
