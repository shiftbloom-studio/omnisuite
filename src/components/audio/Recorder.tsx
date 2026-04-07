import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Player } from './Player';
import { Button } from '../ui/Button';

interface RecorderProps {
  onRecordingComplete: (blob: Blob) => void;
  className?: string;
}

type RecorderPhase = 'idle' | 'recording' | 'recorded';

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export const Recorder: React.FC<RecorderProps> = ({
  onRecordingComplete,
  className = '',
}) => {
  const [phase, setPhase] = useState<RecorderPhase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [recordedUrl, setRecordedUrl] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const prevUrlRef = useRef<string | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        const url = URL.createObjectURL(blob);

        // Clean up previous recording URL
        if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
        prevUrlRef.current = url;

        setRecordedUrl(url);
        setPhase('recorded');
        onRecordingComplete(blob);

        // Stop all tracks
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      };

      mediaRecorder.start();
      setPhase('recording');
      setElapsed(0);

      timerRef.current = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);
    } catch (err) {
      console.error('Failed to access microphone:', err);
    }
  }, [onRecordingComplete]);

  const stopRecording = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  const reRecord = useCallback(() => {
    if (prevUrlRef.current) {
      URL.revokeObjectURL(prevUrlRef.current);
      prevUrlRef.current = null;
    }
    setRecordedUrl(null);
    setElapsed(0);
    setPhase('idle');
  }, []);

  const borderClass =
    phase === 'recording'
      ? 'border-2 border-solid border-[#FF3D00]'
      : phase === 'recorded'
        ? 'border-2 border-solid border-[#222222]'
        : 'border-2 border-dashed border-[#222222]';

  return (
    <div className={`${borderClass} bg-[#0A0A0A] p-4 ${className}`}>
      {phase === 'idle' && (
        <div className="flex flex-col items-center gap-3 py-4">
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#888888"
            strokeWidth="2"
          >
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
          <Button variant="primary" size="md" onClick={startRecording}>
            Record
          </Button>
        </div>
      )}

      {phase === 'recording' && (
        <div className="flex flex-col items-center gap-3 py-4">
          <div className="flex items-center gap-2">
            <span className="block w-[10px] h-[10px] bg-[#EF4444] animate-pulse" />
            <span className="font-mono text-[13px] text-[#E0E0E0] tabular-nums tracking-[1px]">
              {formatElapsed(elapsed)}
            </span>
          </div>
          <Button variant="danger" size="md" onClick={stopRecording}>
            Stop
          </Button>
        </div>
      )}

      {phase === 'recorded' && (
        <div className="flex flex-col gap-3">
          <Player audioUrl={recordedUrl} />
          <Button variant="secondary" size="sm" onClick={reRecord}>
            Re-Record
          </Button>
        </div>
      )}
    </div>
  );
};
