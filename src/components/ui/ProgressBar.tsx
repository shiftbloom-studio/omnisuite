import React from 'react';

interface ProgressBarProps {
  progress: number;
  label?: string;
  className?: string;
  size?: 'sm' | 'md';
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  progress,
  label,
  className = '',
  size = 'md',
}) => {
  const clamped = Math.min(100, Math.max(0, progress));
  const heightClass = size === 'sm' ? 'h-[2px]' : 'h-[4px]';

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && (
        <span className="text-[10px] uppercase tracking-[2px] text-[#888888] font-mono font-bold">
          {label}
        </span>
      )}
      <div className={`bg-[#1a1a1a] w-full ${heightClass}`}>
        <div
          className={`bg-[#FF3D00] ${heightClass} transition-all duration-300`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
};
