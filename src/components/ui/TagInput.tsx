import React, { useState, useRef } from 'react';

interface TagInputProps {
  tags: string[];
  onAdd: (tag: string) => void;
  onRemove: (tag: string) => void;
  placeholder?: string;
  className?: string;
}

export const TagInput: React.FC<TagInputProps> = ({
  tags,
  onAdd,
  onRemove,
  placeholder = 'Add tag...',
  className = '',
}) => {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && input.trim()) {
      e.preventDefault();
      if (!tags.includes(input.trim())) {
        onAdd(input.trim());
      }
      setInput('');
    } else if (e.key === 'Backspace' && input === '' && tags.length > 0) {
      onRemove(tags[tags.length - 1]);
    }
  };

  return (
    <div
      className={[
        'flex flex-wrap items-center gap-1.5 bg-[#080808] border-2 border-[#222222] p-2 cursor-text',
        'focus-within:border-l-4 focus-within:border-l-[#FF3D00] transition-all',
        className,
      ].join(' ')}
      onClick={() => inputRef.current?.focus()}
    >
      {tags.map((tag) => (
        <span
          key={tag}
          className="bg-[#141414] border border-[#222222] text-[12px] text-[#E0E0E0] font-mono px-2 py-1 inline-flex items-center gap-1"
        >
          {tag}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onRemove(tag);
            }}
            className="text-[#888888] hover:text-[#FF3D00] cursor-pointer transition-colors text-[14px] leading-none"
            aria-label={`Remove ${tag}`}
          >
            &times;
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="bg-transparent border-none outline-none text-[#E0E0E0] font-mono text-[14px] flex-1 min-w-[80px] placeholder:text-[#444444]"
      />
    </div>
  );
};
