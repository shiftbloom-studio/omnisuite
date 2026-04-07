import { useState } from "react";
import { Button, Input, Badge } from "../components/ui";

const EXAMPLE_INSTRUCTS = [
  "female, young, warm, american accent",
  "male, deep voice, british accent",
  "female, elderly, whisper",
  "male, child, high pitch",
  "female, low pitch, french accent",
];

export default function VoiceDesign() {
  const [instruct, setInstruct] = useState("");
  const [text, setText] = useState("Hello, this is a test of voice design.");
  const [voiceName, setVoiceName] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  const handlePreview = async () => {
    if (!instruct.trim() || !text.trim()) return;
    setPreviewing(true);
    try {
      // TODO: Wire to designVoicePreview IPC
    } catch (err) {
      console.error("Preview failed:", err);
    } finally {
      setPreviewing(false);
    }
  };

  const handleSave = async () => {
    if (!voiceName.trim() || !instruct.trim()) return;
    setSaving(true);
    try {
      // TODO: Wire to saveDesignedVoice IPC
    } catch (err) {
      console.error("Save failed:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-6 max-w-[800px]">
      <div className="flex items-baseline gap-3 mb-6">
        <h1 className="text-[13px] font-black tracking-[3px] uppercase text-[#FF3D00]">
          VOICE DESIGN
        </h1>
        <div className="flex-1 h-[1px] bg-[#1a1a1a]" />
      </div>

      <p className="text-[13px] text-[#888] mb-6 leading-relaxed">
        Design a voice by describing it in natural language. Specify gender, age,
        pitch, accent, and style.
      </p>

      <div className="mb-6">
        <Input
          label="VOICE DESCRIPTION"
          value={instruct}
          onChange={(e) => setInstruct(e.target.value)}
          placeholder='e.g. "female, young, warm, american accent"'
        />
        <div className="flex flex-wrap gap-2 mt-3">
          {EXAMPLE_INSTRUCTS.map((ex) => (
            <button
              key={ex}
              onClick={() => setInstruct(ex)}
              className="cursor-pointer bg-transparent border-0 p-0"
            >
              <Badge variant={instruct === ex ? "accent" : "muted"}>
                {ex}
              </Badge>
            </button>
          ))}
        </div>
      </div>

      <div className="mb-6">
        <Input
          label="TEST TEXT"
          textarea
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Enter text to preview with this voice..."
        />
      </div>

      <div className="flex gap-2 mb-8">
        <Button
          variant="secondary"
          onClick={handlePreview}
          disabled={!instruct.trim() || !text.trim() || previewing}
          loading={previewing}
        >
          PREVIEW
        </Button>
      </div>

      {audioUrl && (
        <div className="border-2 border-[#222] border-t-[3px] border-t-[#FF3D00] p-4 mb-8">
          <audio src={audioUrl} controls className="w-full" />
        </div>
      )}

      <div className="border-t-[3px] border-[#222] pt-6">
        <div className="flex items-baseline gap-3 mb-4">
          <span className="text-[11px] font-bold tracking-[2px] uppercase text-[#888]">
            SAVE TO LIBRARY
          </span>
          <div className="flex-1 h-[1px] bg-[#1a1a1a]" />
        </div>

        <div className="mb-4">
          <Input
            label="VOICE NAME"
            value={voiceName}
            onChange={(e) => setVoiceName(e.target.value)}
            placeholder="Give this voice a name..."
          />
        </div>

        <Button
          onClick={handleSave}
          disabled={!voiceName.trim() || !instruct.trim() || saving}
          loading={saving}
        >
          SAVE VOICE
        </Button>
      </div>
    </div>
  );
}
