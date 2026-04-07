import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  header?: React.ReactNode;
  footer?: React.ReactNode;
  onClick?: () => void;
  selected?: boolean;
}

export const Card: React.FC<CardProps> = ({
  children,
  className = '',
  header,
  footer,
  onClick,
  selected = false,
}) => {
  return (
    <div
      onClick={onClick}
      className={[
        'bg-[#0F0F0F] border-2 transition-all',
        selected ? 'border-[#FF3D00]' : 'border-[#222222] hover:border-[#333333]',
        onClick ? 'cursor-pointer' : '',
        className,
      ].join(' ')}
    >
      {header && (
        <div className="border-b border-[#222222] p-4">{header}</div>
      )}
      <div className="p-4">{children}</div>
      {footer && (
        <div className="border-t border-[#222222] p-4">{footer}</div>
      )}
    </div>
  );
};
