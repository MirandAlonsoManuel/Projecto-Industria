import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'icon' | 'control' | 'primary' | 'secondary';

interface ButtonCommonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  isActive?: boolean;
}

type ButtonSize =
  | 'small'
  | 'large';

interface ButtonCommonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isActive?: boolean;
  icon?: ReactNode;
}

const sizeClasses: Record<ButtonSize, string> = {
  small: '',
  
  large:
    'font-inter min-h-11 px-4 rounded-full bg-[#393939] text-white text-[15px] gap-3 [&:hover:not(:disabled)]:opacity-[0.8]',
};

const baseClasses =
  'cursor-pointer border-none inline-flex items-center justify-center [transition:filter_0.1s_ease,background_0.1s_ease] disabled:opacity-50 disabled:cursor-not-allowed';

const variantClasses: Record<ButtonVariant, string> = {
  icon: 'w-8 h-8 rounded-lg border border-[#e2e5ea] bg-white text-sm text-[#1f2430] [&:hover:not(:disabled)]:bg-[#f1f2f4]',
  control:
    'w-16 h-16 rounded-full bg-[#2f6fe4] text-white text-xs font-light flex-shrink-0 [&:hover:not(:disabled)]:brightness-[0.92]',
  primary:
    'font-inter py-1.5 px-3  rounded-2xl text-[13px] font-light cursor-pointer bg-[#393939] text-white [&:hover:bg-sky-700',
  secondary:
    'h-9 px-4 rounded-lg bg-white text-[#1f2430] border border-[#e2e5ea] text-[13px] font-light [&:hover:not(:disabled)]:bg-[#f1f2f4]',
};

const controlActiveClass = 'bg-[#d64545]';

export function ButtonCommon({
  variant = 'primary',
  size = 'small',
  isActive = false,
  icon,
  children,
  className = '',
  type = 'button',
  ...rest
}: ButtonCommonProps) {
  const activeClass =
    variant === 'control' && isActive
      ? controlActiveClass
      : '';

  return (
    <button
      type={type}
      className={`
        ${baseClasses}
        ${variantClasses[variant]}
        ${sizeClasses[size]}
        ${activeClass}
        ${className}
      `.trim()}
      {...rest}
    >
      {icon && (
        <span className="shrink-0 flex items-center">
          {icon}
        </span>
      )}

      <span>{children}</span>
    </button>
  );
}
