import type { ReactNode } from 'react';
import { ConnectionStatusBadge } from './ConnectionStatusBadge';
import type { CameraConnectionStatus, Job } from '../../types/indexTypes';
import { ButtonCommon } from '../CommonComponents/Button/ButtonCommon';
import { CameraSparklesIcon, InspectIcon } from '../CommonComponents/Icons/IconCommon.tsx';
import type { Camera, Model } from '../../types/index';
import { connectionBadge, useInferenceConnectionStore } from '../../store/inferenceConnectionStore';

interface TopBarProps {
  title: string;
  onSettings?: () => void;
  /** Ya no se usa: el estado sale del store de conexión WS (T-035) */
  status?: CameraConnectionStatus;
  cameraName?: string;
  rightSlot?: ReactNode;
  camera: Camera;
  model: Model;
  job: Job;
  onToggleInspection: () => void;
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
export function TopBar({cameraName, job, onToggleInspection}: TopBarProps) {
  const isInspectionRunning = job.status === 'running';
  const resolvedCameraName = cameraName ?? '';
  // T-035: estado derivado de los eventos del WebSocket, sin polling REST
  const wsStatus = useInferenceConnectionStore((s) => s.status);
  const wsAttempt = useInferenceConnectionStore((s) => s.attempt);
  const wsLastError = useInferenceConnectionStore((s) => s.lastError);
  const badge = connectionBadge({ status: wsStatus, attempt: wsAttempt, lastError: wsLastError });

  return (
    <header
      className="w-full flex justify-between shrink-0 items-center gap-4 bg-transparent" role="banner">
      <ConnectionStatusBadge
        status={badge.status}
        label={badge.label}
        detail={badge.detail}
        cameraName={resolvedCameraName}
      />
      <div className='flex gap-1.5'>
        <ButtonCommon
            size="large"
            // onClick={() => }
            icon={<CameraSparklesIcon/>}
          >
            Realizar trigger
        </ButtonCommon>
        <ButtonCommon
          variant="primary2nd"
          size ="large"
          isActive={isInspectionRunning}
          onClick={onToggleInspection}
          aria-pressed={isInspectionRunning}
          icon={<InspectIcon/>}
        >
          {/* T-036: el texto refleja el estado del job */}
          {isInspectionRunning
            ? 'Detener inspección'
            : job.status === 'error'
              ? 'Reintentar inspección'
              : 'Iniciar inspección'}
        </ButtonCommon>
      </div>
    </header>
  );
}
