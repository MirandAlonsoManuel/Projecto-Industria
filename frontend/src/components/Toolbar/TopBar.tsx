import type { ReactNode } from 'react';
import { ConnectionStatusBadge } from './ConnectionStatusBadge';
import type { CameraConnectionStatus } from '../../types/indexTypes';
import { ButtonCommon } from '../CommonComponents/Button/ButtonCommon';

interface TopBarProps {
  title: string;
  onSettings?: () => void;
  status?: CameraConnectionStatus;
  cameraName?: string;
  rightSlot?: ReactNode;
}

/**
 * Sustituye el header inline de MainPanel para que el indicador
 * de estado sea un componente propio y reutilizable.
 */
export function TopBar({ title, status, cameraName, rightSlot }: TopBarProps) {
  const resolvedStatus = status ?? 'disconnected';
  const resolvedCameraName = cameraName ?? '';

  return (
    <header
      className="flex h-14 shrink-0 items-center gap-4 border-b border-[#e2e5ea] bg-white px-5"
      role="banner"
    >
      <ConnectionStatusBadge status={resolvedStatus} cameraName={resolvedCameraName} />

      <h1 className="m-0! text-[15px]! font-semibold! tracking-normal! text-[#1f2430]! flex-1 text-center">
        {title}
      </h1>

      {rightSlot}

      <ButtonCommon variant="icon" aria-label="Configuración">
        ⚙
      </ButtonCommon>
    </header>
  );
}
