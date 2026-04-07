import { useState, useEffect, useCallback } from 'react';
import { useVoiceStore } from '../stores/voiceStore';
import { useHistoryStore, type HistoryEntry } from '../stores/historyStore';
import { generateSpeech, listVoices, listHistory } from '../api/commands';
import { defaultVoices } from '../data/defaultVoices';
import { Button, Input, Select, ErrorBanner, Badge } from '../components/ui';
import { Player } from '../components/audio';

const LANGUAGES = [
  { value: 'en-US', label: 'English (US)' },
  { value: 'en-GB', label: 'English (UK)' },
  { value: 'de-DE', label: 'German' },
  { value: 'fr-FR', label: 'French' },
  { value: 'es-ES', label: 'Spanish' },
  { value: 'it-IT', label: 'Italian' },
  { value: 'pt-BR', label: 'Portuguese (BR)' },
  { value: 'ja-JP', label: 'Japanese' },
  { value: 'ko-KR', label: 'Korean' },
  { value: 'zh-CN', label: 'Chinese (Simplified)' },
  { value: 'hi-IN', label: 'Hindi' },
  { value: 'nl-NL', label: 'Dutch' },
  { value: 'pl-PL', label: 'Polish' },
  { value: 'ru-RU', label: 'Russian' },
  { value: 'sv-SE', label: 'Swedish' },
  { value: 'tr-TR', label: 'Turkish' },
  { value: 'ar-SA', label: 'Arabic' },
];

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + '...';
}

function Synthesize() {
  // Stores
  const voices = useVoiceStore((s) => s.voices);
  const activeVoice = useVoiceStore((s) => s.activeVoice);
  const setVoices = useVoiceStore((s) => s.setVoices);
  const setActiveVoice = useVoiceStore((s) => s.setActiveVoice);

  const entries = useHistoryStore((s) => s.entries);
  const setEntries = useHistoryStore((s) => s.setEntries);
  const addEntry = useHistoryStore((s) => s.addEntry);

  // Local state
  const [text, setText] = useState('');
  const [language, setLanguage] = useState('en-US');
  const [generating, setGenerating] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioFilePath, setAudioFilePath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyPlayingId, setHistoryPlayingId] = useState<string | null>(null);

  // Load voices on mount
  useEffect(() => {
    const loadVoices = async () => {
      try {
        const loaded = await listVoices();
        if (loaded.length > 0) {
          setVoices(loaded);
        } else {
          setVoices(defaultVoices);
        }
      } catch {
        // Fallback to defaults if IPC is unavailable
        setVoices(defaultVoices);
      }
    };
    loadVoices();
  }, [setVoices]);

  // Load history on mount
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const loaded = await listHistory();
        setEntries(loaded);
      } catch {
        // History may not be available yet
      }
    };
    loadHistory();
  }, [setEntries]);

  // Auto-set language when voice changes
  useEffect(() => {
    if (activeVoice) {
      setLanguage(activeVoice.language);
    }
  }, [activeVoice]);

  // Set initial active voice
  useEffect(() => {
    if (!activeVoice && voices.length > 0) {
      setActiveVoice(voices[0]);
    }
  }, [voices, activeVoice, setActiveVoice]);

  const voiceOptions = voices.map((v) => ({
    value: v.id,
    label: `${v.name} [${v.language}]`,
  }));

  const handleVoiceChange = useCallback(
    (voiceId: string) => {
      const voice = voices.find((v) => v.id === voiceId) ?? null;
      setActiveVoice(voice);
    },
    [voices, setActiveVoice],
  );

  const handleGenerate = useCallback(async () => {
    if (!activeVoice || !text.trim()) return;

    setGenerating(true);
    setError(null);

    try {
      const result = await generateSpeech({
        voiceId: activeVoice.id,
        text: text.trim(),
      });

      // Convert file path to a URL the webview can load
      const url = `asset://localhost/${result.audio_path.replace(/\\/g, '/')}`;
      setAudioUrl(url);
      setAudioFilePath(result.audio_path);

      // Add to history
      const entry: HistoryEntry = {
        id: result.id,
        text: text.trim(),
        voiceId: activeVoice.id,
        voiceName: activeVoice.name,
        createdAt: new Date().toISOString(),
        duration: result.duration_ms ?? 0,
        filePath: result.audio_path,
      };
      addEntry(entry);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Generation failed. Check sidecar status.';
      setError(message);
    } finally {
      setGenerating(false);
    }
  }, [activeVoice, text, addEntry]);

  const handleDelete = useCallback(() => {
    setAudioUrl(null);
    setAudioFilePath(null);
  }, []);

  const handleDownloadWav = useCallback(() => {
    if (!audioFilePath) return;
    // Trigger download via Tauri shell or file dialog - for now open the path
    window.open(`asset://localhost/${audioFilePath.replace(/\\/g, '/')}`);
  }, [audioFilePath]);

  const handleHistoryPlay = useCallback((entry: HistoryEntry) => {
    const url = `asset://localhost/${entry.filePath.replace(/\\/g, '/')}`;
    setAudioUrl(url);
    setAudioFilePath(entry.filePath);
    setHistoryPlayingId(entry.id);
  }, []);

  return (
    <div className="flex flex-col gap-6 max-w-[720px]">
      {/* Title */}
      <div>
        <h1 className="text-[13px] font-black tracking-[3px] uppercase text-[#FF3D00] mb-3">
          TEXT &rarr; SPEECH
        </h1>
        <hr className="border-[#1a1a1a]" />
      </div>

      {/* Voice selector */}
      <Select
        label="Voice"
        value={activeVoice?.id}
        onChange={handleVoiceChange}
        options={voiceOptions}
        placeholder="Select a voice..."
        searchable
      />

      {/* Active voice info */}
      {activeVoice && (
        <div className="flex items-center gap-2 -mt-3">
          <Badge variant="accent">{activeVoice.type}</Badge>
          {activeVoice.tags.slice(0, 3).map((tag) => (
            <Badge key={tag} variant="default">{tag}</Badge>
          ))}
        </div>
      )}

      {/* Language selector */}
      <Select
        label="Language"
        value={language}
        onChange={setLanguage}
        options={LANGUAGES}
        placeholder="Select language..."
        searchable
      />

      {/* Text input */}
      <Input
        label="Text"
        textarea
        rows={6}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Enter text here... Supports [laughter] and other symbols"
      />

      {/* Character count */}
      <div className="flex items-center justify-between -mt-4">
        <span className="font-mono text-[11px] text-[#555555]">
          {text.length} characters
        </span>
        {text.length > 5000 && (
          <span className="font-mono text-[11px] text-[#EF4444]">
            Max 5000 characters
          </span>
        )}
      </div>

      {/* Generate button */}
      <Button
        variant="primary"
        size="md"
        loading={generating}
        disabled={!activeVoice || !text.trim() || text.length > 5000}
        onClick={handleGenerate}
        className="self-start"
      >
        Generate
      </Button>

      {/* Error */}
      {error && (
        <ErrorBanner
          message={error}
          onDismiss={() => setError(null)}
          onRetry={handleGenerate}
        />
      )}

      {/* Player */}
      {audioUrl && (
        <Player
          audioUrl={audioUrl}
          onDownloadWav={handleDownloadWav}
          onDelete={handleDelete}
        />
      )}

      {/* History section */}
      {entries.length > 0 && (
        <div className="flex flex-col gap-3 mt-4">
          <div>
            <h2 className="text-[12px] font-black tracking-[3px] uppercase text-[#888888] mb-2">
              History
            </h2>
            <hr className="border-[#1a1a1a]" />
          </div>

          <div className="flex flex-col gap-0 max-h-[320px] overflow-y-auto border-2 border-[#222222]">
            {entries.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => handleHistoryPlay(entry)}
                className={[
                  'flex items-center gap-3 p-3 text-left font-mono transition-colors cursor-pointer',
                  'border-b border-[#1a1a1a] last:border-b-0',
                  'hover:bg-[#141414]',
                  historyPlayingId === entry.id
                    ? 'bg-[#141414] border-l-[3px] border-l-[#FF3D00]'
                    : 'bg-[#0A0A0A]',
                ].join(' ')}
              >
                {/* Play icon */}
                <svg
                  width="10"
                  height="12"
                  viewBox="0 0 10 12"
                  fill={historyPlayingId === entry.id ? '#FF3D00' : '#555555'}
                  className="shrink-0"
                >
                  <polygon points="0,0 10,6 0,12" />
                </svg>

                {/* Text preview */}
                <span className="flex-1 text-[12px] text-[#E0E0E0] truncate min-w-0">
                  {truncate(entry.text, 50)}
                </span>

                {/* Voice name */}
                <span className="text-[10px] text-[#555555] uppercase tracking-[1px] shrink-0">
                  {entry.voiceName}
                </span>

                {/* Timestamp */}
                <span className="text-[10px] text-[#444444] tabular-nums shrink-0">
                  {formatTimestamp(entry.createdAt)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default Synthesize;
