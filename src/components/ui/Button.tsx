import React from 'react';

interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'danger';
  size?: 'sm' | 'md';
  disabled?: boolean;
  loading?: boolean;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  children: React.ReactNode;
  className?: string;
  type?: 'button' | 'submit' | 'reset';
}

const variantStyles: Record<string, string> = {
  primary:
    'bg-[#FF3D00] text-white hover:brightness-110',
  secondary:
    'bg-transparent border-2 border-[#222222] text-[#888888] hover:border-[#FF3D00] hover:text-[#E0E0E0]',
  danger:
    'bg-transparent border-2 border-[#EF4444] text-[#EF4444] hover:bg-[#EF4444] hover:text-white',
};

const sizeStyles: Record<string, string> = {
  sm: 'px-3 py-1.5',
  md: 'px-5 py-2.5',
};

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  onClick,
  children,
  className = '',
  type = 'button',
}) => {
  const isDisabled = disabled || loading;

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      className={[
        'uppercase font-mono font-black tracking-[2px] text-[12px] transition-all cursor-pointer',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#FF3D00]',
        variantStyles[variant],
        sizeStyles[size],
        isDisabled ? 'opacity-50 cursor-not-allowed' : '',
        className,
      ].join(' ')}
    >
      <span className="inline-flex items-center gap-2">
        {loading && (
          <span className="inline-block w-3 h-3 border-2 border-current border-t-transparent animate-spin" />
        )}
        {children}
      </span>
    </button>
  );
};
