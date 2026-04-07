import React, { useMemo } from 'react';

interface SliderProps {
  label?: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  className?: string;
}

export const Slider: React.FC<SliderProps> = ({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  className = '',
}) => {
  const percent = useMemo(
    () => ((value - min) / (max - min)) * 100,
    [value, min, max],
  );

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {label && (
        <div className="flex items-center justify-between font-mono">
          <span className="uppercase text-[11px] font-bold tracking-[2px] text-[#888888]">
            {label}
          </span>
          <span className="text-[13px] font-bold text-[#E0E0E0] tracking-[1px]">
            {value}{unit}
          </span>
        </div>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="omnisuite-slider w-full cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#FF3D00]"
        style={{ '--slider-percent': `${percent}%` } as React.CSSProperties}
      />
      <style>{`
        .omnisuite-slider {
          -webkit-appearance: none;
          appearance: none;
          height: 3px;
          background: linear-gradient(
            to right,
            #FF3D00 0%,
            #FF3D00 var(--slider-percent),
            #1a1a1a var(--slider-percent),
            #1a1a1a 100%
          );
          outline: none;
        }
        .omnisuite-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 16px;
          height: 16px;
          background: #FF3D00;
          border: none;
          border-radius: 0;
          cursor: pointer;
        }
        .omnisuite-slider::-moz-range-thumb {
          width: 16px;
          height: 16px;
          background: #FF3D00;
          border: none;
          border-radius: 0;
          cursor: pointer;
        }
      `}</style>
    </div>
  );
};
