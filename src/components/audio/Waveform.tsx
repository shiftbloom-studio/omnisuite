import React, { useMemo, useCallback, useRef } from 'react';

interface WaveformProps {
  audioData: Float32Array | null;
  progress: number;
  onSeek: (position: number) => void;
  className?: string;
}

const BAR_COUNT = 60;

function generatePlaceholderBars(): number[] {
  const bars: number[] = [];
  for (let i = 0; i < BAR_COUNT; i++) {
    bars.push(0.05 + Math.random() * 0.15);
  }
  return bars;
}

const placeholderBars = generatePlaceholderBars();

export const Waveform: React.FC<WaveformProps> = ({
  audioData,
  progress,
  onSeek,
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const bars = useMemo(() => {
    if (!audioData || audioData.length === 0) {
      return placeholderBars;
    }

    const result: number[] = [];
    const samplesPerBar = Math.floor(audioData.length / BAR_COUNT);

    for (let i = 0; i < BAR_COUNT; i++) {
      let peak = 0;
      const start = i * samplesPerBar;
      for (let j = start; j < start + samplesPerBar && j < audioData.length; j++) {
        const abs = Math.abs(audioData[j]);
        if (abs > peak) peak = abs;
      }
      result.push(peak);
    }

    return result;
  }, [audioData]);

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const position = Math.max(0, Math.min(1, x / rect.width));
      onSeek(position);
    },
    [onSeek],
  );

  const hasData = audioData !== null && audioData.length > 0;
  const progressIndex = Math.floor(progress * BAR_COUNT);

  return (
    <div
      ref={containerRef}
      onClick={handleClick}
      className={`h-[48px] w-full flex items-end gap-[1px] cursor-pointer select-none ${className}`}
    >
      {bars.map((amplitude, i) => {
        const heightPercent = Math.max(2 / 48, amplitude) * 100;
        const isPlayed = hasData && i < progressIndex;

        return (
          <div
            key={i}
            className="flex-1 transition-colors duration-75"
            style={{
              height: `${Math.max(4, heightPercent)}%`,
              minHeight: '2px',
              backgroundColor: hasData
                ? isPlayed
                  ? '#FF3D00'
                  : '#333333'
                : '#1a1a1a',
            }}
          />
        );
      })}
    </div>
  );
};
