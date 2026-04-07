import React from 'react';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'accent' | 'success' | 'muted';
  className?: string;
}

const variantStyles: Record<string, string> = {
  default: 'bg-[#141414] text-[#888888] border border-[#222222]',
  accent:  'bg-[#FF3D00]/10 text-[#FF3D00] border border-[#FF3D00]/30',
  success: 'bg-[#22C55E]/10 text-[#22C55E] border border-[#22C55E]/30',
  muted:   'bg-[#0F0F0F] text-[#555555] border border-[#1a1a1a]',
};

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  className = '',
}) => {
  return (
    <span
      className={[
        'inline-block text-[10px] uppercase tracking-[2px] font-bold font-mono px-2 py-1',
        variantStyles[variant],
        className,
      ].join(' ')}
    >
      {children}
    </span>
  );
};
