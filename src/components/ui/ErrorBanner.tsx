import React from 'react';
import { Button } from './Button';

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  message,
  onRetry,
  onDismiss,
  className = '',
}) => {
  return (
    <div
      className={[
        'bg-[#EF4444]/10 border-2 border-[#EF4444] p-4 flex items-center gap-3',
        className,
      ].join(' ')}
      role="alert"
    >
      <svg
        className="w-5 h-5 text-[#EF4444] shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M12 8v4m0 4h.01" />
      </svg>

      <span className="text-[#EF4444] font-mono text-[13px] flex-1">{message}</span>

      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}

      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="text-[#EF4444] hover:text-white transition-colors cursor-pointer p-1"
          aria-label="Dismiss"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="square" d="M6 6l12 12M6 18L18 6" />
          </svg>
        </button>
      )}
    </div>
  );
};
