import React, { useState, useRef, useCallback } from 'react';

interface DropZoneProps {
  onFiles: (files: File[]) => void;
  accept?: string;
  label?: string;
  className?: string;
  multiple?: boolean;
}

export const DropZone: React.FC<DropZoneProps> = ({
  onFiles,
  accept,
  label = 'Drop files here or click to browse',
  className = '',
  multiple = false,
}) => {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) {
      setDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current = 0;
      setDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        onFiles(multiple ? files : [files[0]]);
      }
    },
    [onFiles, multiple],
  );

  const handleClick = () => inputRef.current?.click();

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) {
      onFiles(files);
    }
    e.target.value = '';
  };

  return (
    <div
      onClick={handleClick}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className={[
        'border-2 border-dashed p-8 text-center cursor-pointer transition-all',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#FF3D00]',
        dragging
          ? 'border-[#FF3D00] bg-[#FF3D00]/5'
          : 'border-[#222222] hover:border-[#333333]',
        className,
      ].join(' ')}
      tabIndex={0}
      role="button"
      aria-label={label}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={handleChange}
        className="hidden"
      />
      <div className="flex flex-col items-center gap-3">
        <svg
          className={`w-8 h-8 ${dragging ? 'text-[#FF3D00]' : 'text-[#888888]'}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="square" d="M12 16V4m0 0l-4 4m4-4l4 4" />
          <path strokeLinecap="square" d="M4 18h16" />
        </svg>
        <span className="text-[#888888] font-mono text-[13px] uppercase tracking-[1px]">
          {label}
        </span>
      </div>
    </div>
  );
};
