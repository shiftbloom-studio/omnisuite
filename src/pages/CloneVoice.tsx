import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Input, Select, TagInput, DropZone, ErrorBanner } from "@/components/ui";
import { Recorder } from "@/components/audio/Recorder";
import { cloneVoiceTest, saveClonedVoice } from "@/api/commands";
import { useVoiceStore } from "@/stores/voiceStore";

const STEPS = ["UPLOAD", "TRANSCRIPT", "NAME & TAG", "TEST & SAVE"] as const;

const LANGUAGE_OPTIONS = [
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

function CloneVoice() {
  const navigate = useNavigate();
  const addVoice = useVoiceStore((s) => s.addVoice);

  // Wizard state
  const [currentStep, setCurrentStep] = useState(1);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [transcript, setTranscript] = useState("");
  const [voiceName, setVoiceName] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [language, setLanguage] = useState("en-US");
  const [testText, setTestText] = useState(
    "Hello, this is a test of my new cloned voice.",
  );
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testAudioUrl, setTestAudioUrl] = useState<string | null>(null);
  const [inputMode, setInputMode] = useState<"upload" | "record">("upload");

  const audioRef = useRef<HTMLAudioElement>(null);

  // Helpers
  const hasAudio = audioFile !== null || audioBlob !== null;
  const audioName = audioFile?.name ?? (audioBlob ? "Recording.webm" : null);

  const getAudioPath = useCallback((): string => {
    // In a Tauri app, the file path would be resolved from the File object.
    // For files, use webkitRelativePath or name; for blobs, use a temp path.
    if (audioFile) return audioFile.name;
    return "recording.webm";
  }, [audioFile]);

  const canAdvance = (): boolean => {
    switch (currentStep) {
      case 1:
        return hasAudio;
      case 2:
        return transcript.trim().length > 10;
      case 3:
        return voiceName.trim().length > 0;
      case 4:
        return true;
      default:
        return false;
    }
  };

  const handleNext = () => {
    if (currentStep < 4 && canAdvance()) {
      setCurrentStep((s) => s + 1);
      setError(null);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep((s) => s - 1);
      setError(null);
    }
  };

  const handleFileDrop = (files: File[]) => {
    if (files.length > 0) {
      setAudioFile(files[0]);
      setAudioBlob(null);
      setError(null);
    }
  };

  const handleRecorded = (blob: Blob) => {
    setAudioBlob(blob);
    setAudioFile(null);
    setError(null);
  };

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setTestAudioUrl(null);
    try {
      const result = await cloneVoiceTest({
        audioPath: getAudioPath(),
        text: testText,
      });
      setTestAudioUrl(result.filePath);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Voice test failed.");
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const voice = await saveClonedVoice({
        audioPath: getAudioPath(),
        name: voiceName.trim(),
        language,
        tags,
      });
      addVoice(voice);
      navigate("/library");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save voice.");
    } finally {
      setSaving(false);
    }
  };

  // --- Render ---

  const renderStepIndicator = () => (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((label, i) => {
        const stepNum = i + 1;
        const isActive = stepNum === currentStep;
        const isComplete = stepNum < currentStep;
        return (
          <div key={label} className="flex items-center">
            {i > 0 && (
              <div
                className={[
                  "w-8 h-[2px]",
                  isComplete ? "bg-[#FF3D00]" : "bg-[#222222]",
                ].join(" ")}
              />
            )}
            <div className="flex items-center gap-2">
              <div
                className={[
                  "w-7 h-7 flex items-center justify-center text-[11px] font-mono font-black border-2",
                  isActive
                    ? "border-[#FF3D00] bg-[#FF3D00] text-white"
                    : isComplete
                      ? "border-[#FF3D00] bg-transparent text-[#FF3D00]"
                      : "border-[#222222] bg-transparent text-[#555555]",
                ].join(" ")}
              >
                {isComplete ? (
                  <svg
                    className="w-3.5 h-3.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path
                      strokeLinecap="square"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                ) : (
                  stepNum
                )}
              </div>
              <span
                className={[
                  "text-[10px] uppercase tracking-[2px] font-mono font-bold hidden sm:inline",
                  isActive
                    ? "text-[#FF3D00]"
                    : isComplete
                      ? "text-[#E0E0E0]"
                      : "text-[#555555]",
                ].join(" ")}
              >
                {label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );

  const renderStep1 = () => (
    <div className="flex flex-col gap-6">
      {/* Tab toggle */}
      <div className="flex border-2 border-[#222222] w-fit">
        <button
          type="button"
          onClick={() => setInputMode("upload")}
          className={[
            "px-5 py-2 text-[11px] uppercase tracking-[2px] font-mono font-bold transition-all cursor-pointer",
            inputMode === "upload"
              ? "bg-[#FF3D00] text-white"
              : "bg-transparent text-[#888888] hover:text-[#E0E0E0]",
          ].join(" ")}
        >
          UPLOAD
        </button>
        <button
          type="button"
          onClick={() => setInputMode("record")}
          className={[
            "px-5 py-2 text-[11px] uppercase tracking-[2px] font-mono font-bold transition-all cursor-pointer",
            inputMode === "record"
              ? "bg-[#FF3D00] text-white"
              : "bg-transparent text-[#888888] hover:text-[#E0E0E0]",
          ].join(" ")}
        >
          RECORD
        </button>
      </div>

      {inputMode === "upload" ? (
        <DropZone
          onFiles={handleFileDrop}
          accept=".wav,.mp3,.flac"
          label="Drop WAV, MP3, or FLAC file here or click to browse"
        />
      ) : (
        <Recorder onRecordingComplete={handleRecorded} />
      )}

      {hasAudio && (
        <div className="flex items-center gap-3 bg-[#0F0F0F] border-2 border-[#222222] p-4">
          <svg
            className="w-5 h-5 text-[#22C55E] shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="square" d="M5 13l4 4L19 7" />
          </svg>
          <div className="flex flex-col">
            <span className="text-[13px] font-mono text-[#E0E0E0]">
              {audioName}
            </span>
            <span className="text-[11px] font-mono text-[#888888] uppercase tracking-[1px]">
              Audio ready
            </span>
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <Button disabled={!canAdvance()} onClick={handleNext}>
          NEXT
        </Button>
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div className="flex flex-col gap-6">
      <Input
        label="TRANSCRIPT"
        textarea
        rows={6}
        value={transcript}
        onChange={(e) => setTranscript(e.target.value)}
        placeholder="Enter the exact text spoken in your reference audio..."
        error={
          transcript.length > 0 && transcript.trim().length <= 10
            ? "Transcript must be longer than 10 characters"
            : undefined
        }
      />
      <p className="text-[11px] text-[#555555] font-mono tracking-[1px] leading-relaxed">
        Enter the exact text spoken in your reference audio. This is required
        for accurate voice cloning.
      </p>

      <div className="flex justify-between">
        <Button variant="secondary" onClick={handleBack}>
          BACK
        </Button>
        <Button disabled={!canAdvance()} onClick={handleNext}>
          NEXT
        </Button>
      </div>
    </div>
  );

  const renderStep3 = () => (
    <div className="flex flex-col gap-6">
      <Input
        label="VOICE NAME"
        value={voiceName}
        onChange={(e) => setVoiceName(e.target.value)}
        placeholder="e.g. My Narrator Voice"
        error={
          voiceName.length > 0 && voiceName.trim().length === 0
            ? "Voice name is required"
            : undefined
        }
      />

      <div className="flex flex-col gap-1.5">
        <label className="uppercase text-[11px] font-bold tracking-[2px] text-[#888888] font-mono">
          TAGS
        </label>
        <TagInput
          tags={tags}
          onAdd={(t) => setTags((prev) => [...prev, t])}
          onRemove={(t) => setTags((prev) => prev.filter((x) => x !== t))}
          placeholder='e.g. "female", "warm", "narrator"'
        />
      </div>

      <Select
        label="LANGUAGE"
        value={language}
        onChange={(v) => setLanguage(v)}
        options={LANGUAGE_OPTIONS}
        searchable
      />

      <div className="flex justify-between">
        <Button variant="secondary" onClick={handleBack}>
          BACK
        </Button>
        <Button disabled={!canAdvance()} onClick={handleNext}>
          NEXT
        </Button>
      </div>
    </div>
  );

  const renderStep4 = () => (
    <div className="flex flex-col gap-6">
      {/* Summary */}
      <div className="bg-[#0F0F0F] border-2 border-[#222222] p-5 flex flex-col gap-3">
        <span className="text-[10px] uppercase tracking-[2px] font-mono font-bold text-[#888888]">
          VOICE SUMMARY
        </span>
        <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2">
          <span className="text-[11px] uppercase tracking-[1px] font-mono text-[#555555]">
            NAME
          </span>
          <span className="text-[13px] font-mono text-[#E0E0E0]">
            {voiceName}
          </span>

          <span className="text-[11px] uppercase tracking-[1px] font-mono text-[#555555]">
            LANGUAGE
          </span>
          <span className="text-[13px] font-mono text-[#E0E0E0]">
            {LANGUAGE_OPTIONS.find((o) => o.value === language)?.label ?? language}
          </span>

          <span className="text-[11px] uppercase tracking-[1px] font-mono text-[#555555]">
            TAGS
          </span>
          <div className="flex flex-wrap gap-1.5">
            {tags.length > 0 ? (
              tags.map((tag) => (
                <span
                  key={tag}
                  className="bg-[#141414] border border-[#222222] text-[10px] text-[#888888] font-mono px-2 py-0.5 uppercase tracking-[1px]"
                >
                  {tag}
                </span>
              ))
            ) : (
              <span className="text-[12px] font-mono text-[#555555]">
                None
              </span>
            )}
          </div>

          <span className="text-[11px] uppercase tracking-[1px] font-mono text-[#555555]">
            SOURCE
          </span>
          <span className="text-[13px] font-mono text-[#E0E0E0]">
            {audioName}
          </span>
        </div>
      </div>

      {/* Test section */}
      <div className="flex flex-col gap-3">
        <span className="text-[10px] uppercase tracking-[2px] font-mono font-bold text-[#888888]">
          TEST VOICE
        </span>
        <Input
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          placeholder="Enter test sentence..."
        />
        <Button
          variant="secondary"
          onClick={handleTest}
          loading={testing}
          disabled={!testText.trim()}
        >
          TEST
        </Button>

        {testAudioUrl && (
          <div className="bg-[#0F0F0F] border-2 border-[#222222] p-3">
            <audio
              ref={audioRef}
              src={testAudioUrl}
              controls
              className="w-full h-8 [&::-webkit-media-controls-panel]:bg-[#141414]"
            />
          </div>
        )}
      </div>

      {error && (
        <ErrorBanner
          message={error}
          onDismiss={() => setError(null)}
        />
      )}

      <div className="flex justify-between">
        <Button variant="secondary" onClick={handleBack}>
          BACK
        </Button>
        <Button onClick={handleSave} loading={saving}>
          SAVE VOICE
        </Button>
      </div>
    </div>
  );

  return (
    <div className="max-w-[640px]">
      <h1 className="text-[13px] font-black tracking-[3px] uppercase text-[#FF3D00] mb-1">
        CLONE VOICE
      </h1>
      <p className="text-[11px] text-[#555555] font-mono tracking-[1px] mb-6">
        Create a new voice from reference audio in 4 steps.
      </p>
      <hr className="border-[#1a1a1a] mb-6" />

      {renderStepIndicator()}

      {error && currentStep !== 4 && (
        <ErrorBanner
          message={error}
          onDismiss={() => setError(null)}
          className="mb-6"
        />
      )}

      {currentStep === 1 && renderStep1()}
      {currentStep === 2 && renderStep2()}
      {currentStep === 3 && renderStep3()}
      {currentStep === 4 && renderStep4()}
    </div>
  );
}

export default CloneVoice;
