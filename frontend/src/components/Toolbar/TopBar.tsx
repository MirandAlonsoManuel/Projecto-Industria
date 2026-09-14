import type { ReactNode } from 'react';
import { ConnectionStatusBadge } from './ConnectionStatusBadge';
import type { CameraConnectionStatus } from '../../types/indexTypes';
import { ButtonCommon } from '../CommonComponents/Button/ButtonCommon';
import { CameraSparklesIcon } from '../CommonComponents/Icons/IconCommon.tsx';
import type { Camera, Model } from '../../types/index';

interface TopBarProps {
  title: string;
  onSettings?: () => void;
  status?: CameraConnectionStatus;
  cameraName?: string;
  rightSlot?: ReactNode;
  camera: Camera;
  model: Model;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 py-1.5 border-b border-[#f1f2f4] text-[13px]">
      <span className="text-[#6b7280]">{label}</span>
      <span className="font-semibold text-right">{value}</span>
    </div>
  );
}

/**
 * Sustituye el header inline de MainPanel para que el indicador
 * de estado sea un componente propio y reutilizable.
 */
export function TopBar({ title, status, cameraName, rightSlot, camera }: TopBarProps) {
  const resolvedStatus = status ?? 'disconnected';
  const resolvedCameraName = cameraName ?? '';

  return (
    <header
      className="w-full flex justify-between shrink-0 items-center gap-4 bg-transparent" role="banner">
      <ConnectionStatusBadge status={resolvedStatus} cameraName={resolvedCameraName}/>
      <ButtonCommon
          size="large"
          // onClick={() => }
          icon={<CameraSparklesIcon/>}
        >
          Realizar trigger
        </ButtonCommon>
    </header>
  );
}
