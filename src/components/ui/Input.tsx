import React, { forwardRef } from 'react';

interface InputProps {
  label?: string;
  value?: string;
  onChange?: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  placeholder?: string;
  type?: 'text' | 'password' | 'number';
  textarea?: boolean;
  rows?: number;
  disabled?: boolean;
  className?: string;
  error?: string;
}

const fieldStyles = [
  'bg-[#080808] border-2 border-[#222222] text-[#E0E0E0] font-mono text-[14px] p-3 w-full',
  'focus:border-l-4 focus:border-l-[#FF3D00] focus:outline-none transition-all',
  'placeholder:text-[#444444]',
  'focus-visible:outline-none',
  'disabled:opacity-50 disabled:cursor-not-allowed',
].join(' ');

export const Input = forwardRef<HTMLInputElement | HTMLTextAreaElement, InputProps>(
  (
    {
      label,
      value,
      onChange,
      placeholder,
      type = 'text',
      textarea = false,
      rows = 4,
      disabled = false,
      className = '',
      error,
    },
    ref,
  ) => {
    const errorBorder = error ? 'border-[#EF4444]' : '';

    return (
      <div className={`flex flex-col gap-1.5 ${className}`}>
        {label && (
          <label className="uppercase text-[11px] font-bold tracking-[2px] text-[#888888] font-mono">
            {label}
          </label>
        )}
        {textarea ? (
          <textarea
            ref={ref as React.Ref<HTMLTextAreaElement>}
            value={value}
            onChange={onChange}
            placeholder={placeholder}
            rows={rows}
            disabled={disabled}
            className={`${fieldStyles} ${errorBorder} resize-y`}
          />
        ) : (
          <input
            ref={ref as React.Ref<HTMLInputElement>}
            type={type}
            value={value}
            onChange={onChange}
            placeholder={placeholder}
            disabled={disabled}
            className={`${fieldStyles} ${errorBorder}`}
          />
        )}
        {error && (
          <span className="text-[#EF4444] text-[11px] font-mono tracking-[1px]">
            {error}
          </span>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';
