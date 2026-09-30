import type { ButtonHTMLAttributes } from 'react';

type ButtonVariant = 'icon' | 'control' | 'primary' | 'secondary';

interface ButtonCommonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  isActive?: boolean;
}

const baseClasses =
  'cursor-pointer [font-family:inherit] border-none inline-flex items-center justify-center [transition:filter_0.1s_ease,background_0.1s_ease] disabled:opacity-50 disabled:cursor-not-allowed';

const variantClasses: Record<ButtonVariant, string> = {
  icon: 'w-8 h-8 rounded-lg border border-[#e2e5ea] bg-white text-sm text-[#1f2430] [&:hover:not(:disabled)]:bg-[#f1f2f4]',
  control:
    'w-16 h-16 rounded-full bg-[#2f6fe4] text-white text-xs font-bold flex-shrink-0 [&:hover:not(:disabled)]:brightness-[0.92]',
  primary:
    'h-9 px-4 rounded-lg bg-[#2f6fe4] text-white text-[13px] font-semibold [&:hover:not(:disabled)]:brightness-[0.92]',
  secondary:
    'h-9 px-4 rounded-lg bg-white text-[#1f2430] border border-[#e2e5ea] text-[13px] font-medium [&:hover:not(:disabled)]:bg-[#f1f2f4]',
};

const controlActiveClass = 'bg-[#d64545]';

export function ButtonCommon({
  variant = 'primary',
  isActive = false,
  children,
  className = '',
  type = 'button',
  ...rest
}: ButtonCommonProps) {
  const activeClass = variant === 'control' && isActive ? controlActiveClass : '';

  return (
    <button
      type={type}
      className={`${baseClasses} ${variantClasses[variant]} ${activeClass} ${className}`.trim()}
      {...rest}
    >
      {children}
    </button>
  );
}
