import React from 'react';
import { ProgressBar } from '../ui/ProgressBar';
import { ErrorBanner } from '../ui/ErrorBanner';

interface LoadingScreenProps {
  status: 'starting' | 'downloading' | 'loading' | 'error';
  progress?: number;
  errorMessage?: string;
  onRetry?: () => void;
}

export const LoadingScreen: React.FC<LoadingScreenProps> = ({
  status,
  progress = 0,
  errorMessage,
  onRetry,
}) => {
  return (
    <div className="fixed inset-0 bg-[#0A0A0A] z-50 flex flex-col items-center justify-center gap-8 p-8">
      {/* Branding */}
      <div className="flex flex-col items-center gap-2">
        <span className="text-[#FF3D00] font-mono font-black text-[28px] tracking-[6px] uppercase">
          OmniSuite
        </span>
        <div className="w-12 h-[2px] bg-[#FF3D00]" />
      </div>

      {/* Status content */}
      <div className="w-full max-w-md flex flex-col items-center gap-6">
        {status === 'starting' && (
          <span className="text-[#888888] font-mono text-[12px] uppercase tracking-[3px] animate-pulse">
            Initializing...
          </span>
        )}

        {status === 'downloading' && (
          <div className="w-full flex flex-col items-center gap-4">
            <span className="text-[#888888] font-mono text-[12px] uppercase tracking-[3px]">
              Downloading Model
            </span>
            <ProgressBar progress={progress * 100} className="w-full" />
            <span className="text-[#555555] font-mono text-[11px] tracking-[1px]">
              {Math.round(progress * 100)}%
            </span>
          </div>
        )}

        {status === 'loading' && (
          <div className="flex flex-col items-center gap-4">
            <span className="text-[#888888] font-mono text-[12px] uppercase tracking-[3px]">
              Loading Model...
            </span>
            <div className="w-6 h-6 border-2 border-[#FF3D00] border-t-transparent animate-spin" />
          </div>
        )}

        {status === 'error' && errorMessage && (
          <ErrorBanner
            message={errorMessage}
            onRetry={onRetry}
            className="w-full"
          />
        )}
      </div>
    </div>
  );
};
