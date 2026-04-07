import React, { forwardRef, useState, useRef, useEffect, useCallback } from 'react';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  label?: string;
  value?: string;
  onChange?: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  searchable?: boolean;
  className?: string;
}

export const Select = forwardRef<HTMLDivElement, SelectProps>(
  ({ label, value, onChange, options, placeholder = 'Select...', searchable = false, className = '' }, ref) => {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);

    const selectedOption = options.find((o) => o.value === value);

    const filtered = searchable && search
      ? options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()))
      : options;

    const handleClickOutside = useCallback((e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch('');
      }
    }, []);

    useEffect(() => {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [handleClickOutside]);

    useEffect(() => {
      if (open && searchable && searchInputRef.current) {
        searchInputRef.current.focus();
      }
    }, [open, searchable]);

    const handleSelect = (optionValue: string) => {
      onChange?.(optionValue);
      setOpen(false);
      setSearch('');
    };

    return (
      <div ref={ref} className={`flex flex-col gap-1.5 ${className}`}>
        {label && (
          <label className="uppercase text-[11px] font-bold tracking-[2px] text-[#888888] font-mono">
            {label}
          </label>
        )}
        <div ref={containerRef} className="relative">
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className={[
              'bg-[#080808] border-2 border-[#222222] text-[14px] font-mono p-3 w-full text-left',
              'flex items-center justify-between transition-all cursor-pointer',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#FF3D00]',
              open ? 'border-l-4 border-l-[#FF3D00]' : '',
              selectedOption ? 'text-[#E0E0E0]' : 'text-[#444444]',
            ].join(' ')}
          >
            <span>{selectedOption ? selectedOption.label : placeholder}</span>
            <svg
              className={`w-4 h-4 text-[#888888] transition-transform ${open ? 'rotate-180' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="square" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {open && (
            <div className="absolute z-50 left-0 right-0 mt-0 bg-[#0F0F0F] border-2 border-[#222222] max-h-[300px] overflow-y-auto">
              {searchable && (
                <div className="p-2 border-b border-[#222222]">
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search..."
                    className="bg-[#080808] border border-[#222222] text-[#E0E0E0] font-mono text-[13px] p-2 w-full focus:outline-none placeholder:text-[#444444]"
                  />
                </div>
              )}
              {filtered.length === 0 ? (
                <div className="p-3 text-[#444444] text-[13px] font-mono">No results</div>
              ) : (
                filtered.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleSelect(option.value)}
                    className={[
                      'w-full text-left p-3 font-mono text-[14px] cursor-pointer transition-colors',
                      'hover:bg-[#141414]',
                      option.value === value
                        ? 'border-l-4 border-l-[#FF3D00] text-[#E0E0E0]'
                        : 'text-[#888888]',
                    ].join(' ')}
                  >
                    {option.label}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    );
  },
);

Select.displayName = 'Select';
