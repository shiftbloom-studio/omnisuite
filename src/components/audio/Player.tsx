import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Waveform } from './Waveform';
import { Button } from '../ui/Button';

interface PlayerProps {
  audioUrl: string | null;
  onDownloadWav?: () => void;
  onDownloadMp3?: () => void;
  onDelete?: () => void;
  className?: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export const Player: React.FC<PlayerProps> = ({
  audioUrl,
  onDownloadWav,
  onDownloadMp3,
  onDelete,
  className = '',
}) => {
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [waveformData, setWaveformData] = useState<Float32Array | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const animFrameRef = useRef<number>(0);

  // Decode audio for waveform visualization
  useEffect(() => {
    if (!audioUrl) {
      setWaveformData(null);
      setPlaying(false);
      setProgress(0);
      setDuration(0);
      setCurrentTime(0);
      return;
    }

    let cancelled = false;

    const loadAudio = async () => {
      try {
        const response = await fetch(audioUrl);
        const arrayBuffer = await response.arrayBuffer();
        const audioContext = new AudioContext();
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        if (!cancelled) {
          setWaveformData(audioBuffer.getChannelData(0));
          setDuration(audioBuffer.duration);
        }
        await audioContext.close();
      } catch (err) {
        console.error('Failed to decode audio for waveform:', err);
      }
    };

    loadAudio();

    return () => {
      cancelled = true;
    };
  }, [audioUrl]);

  // Set up HTML audio element
  useEffect(() => {
    if (!audioUrl) return;

    const audio = new Audio(audioUrl);
    audioRef.current = audio;

    audio.addEventListener('ended', () => {
      setPlaying(false);
      setProgress(1);
    });

    audio.addEventListener('loadedmetadata', () => {
      if (audio.duration && isFinite(audio.duration)) {
        setDuration(audio.duration);
      }
    });

    return () => {
      audio.pause();
      audio.src = '';
      audioRef.current = null;
    };
  }, [audioUrl]);

  // Animation frame for progress tracking
  useEffect(() => {
    const tick = () => {
      const audio = audioRef.current;
      if (audio && playing) {
        const t = audio.currentTime;
        const d = audio.duration || 1;
        setCurrentTime(t);
        setProgress(t / d);
      }
      animFrameRef.current = requestAnimationFrame(tick);
    };

    if (playing) {
      animFrameRef.current = requestAnimationFrame(tick);
    }

    return () => {
      cancelAnimationFrame(animFrameRef.current);
    };
  }, [playing]);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      // If ended, restart
      if (progress >= 1) {
        audio.currentTime = 0;
        setProgress(0);
        setCurrentTime(0);
      }
      audio.play().then(() => setPlaying(true)).catch(console.error);
    }
  }, [playing, progress]);

  const handleSeek = useCallback(
    (position: number) => {
      const audio = audioRef.current;
      if (!audio || !duration) return;
      audio.currentTime = position * duration;
      setCurrentTime(audio.currentTime);
      setProgress(position);
    },
    [duration],
  );

  if (!audioUrl) return null;

  return (
    <div
      className={`border-2 border-[#222222] border-t-[3px] border-t-[#FF3D00] bg-[#0A0A0A] ${className}`}
    >
      {/* Main controls row */}
      <div className="flex items-center gap-3 p-3">
        {/* Play/Pause button */}
        <button
          type="button"
          onClick={togglePlay}
          className="w-[32px] h-[32px] bg-[#FF3D00] flex items-center justify-center shrink-0 cursor-pointer hover:brightness-110 transition-all"
        >
          {playing ? (
            <svg width="12" height="14" viewBox="0 0 12 14" fill="white">
              <rect x="0" y="0" width="4" height="14" />
              <rect x="8" y="0" width="4" height="14" />
            </svg>
          ) : (
            <svg width="12" height="14" viewBox="0 0 12 14" fill="white">
              <polygon points="0,0 12,7 0,14" />
            </svg>
          )}
        </button>

        {/* Waveform */}
        <div className="flex-1 min-w-0">
          <Waveform
            audioData={waveformData}
            progress={progress}
            onSeek={handleSeek}
          />
        </div>

        {/* Time display */}
        <span className="font-mono text-[11px] text-[#555555] shrink-0 tabular-nums">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>

      {/* Bottom row: actions */}
      {(onDownloadWav || onDownloadMp3 || onDelete) && (
        <div className="flex items-center gap-2 px-3 pb-3">
          {onDownloadWav && (
            <Button variant="secondary" size="sm" onClick={onDownloadWav}>
              WAV
            </Button>
          )}
          {onDownloadMp3 && (
            <Button variant="secondary" size="sm" onClick={onDownloadMp3}>
              MP3
            </Button>
          )}
          <div className="flex-1" />
          {onDelete && (
            <Button variant="danger" size="sm" onClick={onDelete}>
              Delete
            </Button>
          )}
        </div>
      )}
    </div>
  );
};
