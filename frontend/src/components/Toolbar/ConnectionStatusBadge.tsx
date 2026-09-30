import type { CameraConnectionStatus } from '../../types/indexTypes';

/**
 * T-010 — Semáforo visual de estado de conexión de cámara.
 *
 * Mapeo de colores:
 *   connected      → verde  ●
 *   connecting     → amarillo (animado pulsando)
 *   disconnecting  → amarillo (animado pulsando)
 *   disconnected   → gris   ●
 *   error          → rojo   ●
 *
 * El componente es puramente presentacional: recibe el status y
 * lo muestra. El valor real viene del store vía el hook useCameraStatus.
 */

interface ConnectionStatusBadgeProps {
  status: CameraConnectionStatus;
  /** Nombre legible de la cámara activa, para mostrarlo junto al indicador */
  cameraName?: string;
  /** Permite ocultar la etiqueta de texto y mostrar solo el punto (para barras compactas) */
  compact?: boolean;
}

const badgeClasses =
  'inline-flex select-none items-center gap-[7px] rounded-full bg-[#f1f2f4] px-3 py-1 text-xs font-semibold';

const dotBaseClasses = 'h-[9px] w-[9px] shrink-0 rounded-full';

const dotColorClasses: Record<CameraConnectionStatus, string> = {
  connected: 'bg-[#1e9e63] shadow-[0_0_0_3px_rgba(30,158,99,0.18)]',
  connecting: 'bg-[#e0a020] shadow-[0_0_0_3px_rgba(224,160,32,0.18)]',
  disconnecting: 'bg-[#e0a020] shadow-[0_0_0_3px_rgba(224,160,32,0.18)]',
  disconnected: 'bg-[#9aa3af]',
  error: 'bg-[#d64545] shadow-[0_0_0_3px_rgba(214,69,69,0.18)]',
};

const pulsingClass = '[animation:pulse_1.1s_ease-in-out_infinite]';

const labelClasses = 'leading-none text-[#1f2430]';

const cameraNameClasses = 'font-normal text-[#6b7280]';

const STATUS_META: Record<CameraConnectionStatus, { label: string; colorClass: string }> = {
  connected: { label: 'Conectado', colorClass: 'dotGreen' },
  connecting: { label: 'Conectando...', colorClass: 'dotYellow' },
  disconnecting: { label: 'Desconectando...', colorClass: 'dotYellow' },
  disconnected: { label: 'Sin conexión', colorClass: 'dotGray' },
  error: { label: 'Error de cámara', colorClass: 'dotRed' },
};

export function ConnectionStatusBadge({
  status,
  cameraName,
  compact = false,
}: ConnectionStatusBadgeProps) {
  const meta = STATUS_META[status];
  const isPulsing = status === 'connecting' || status === 'disconnecting';

  return (
    <span
      className={badgeClasses}
      role="status"
      aria-live="polite"
      aria-label={`Estado de cámara: ${meta.label}`}
    >
      <span
        className={`${dotBaseClasses} ${dotColorClasses[status]} ${isPulsing ? pulsingClass : ''}`}
      />
      {!compact && (
        <span className={labelClasses}>
          {meta.label}
          {cameraName && status === 'connected' && (
            <span className={cameraNameClasses}> — {cameraName}</span>
          )}
        </span>
      )}
    </span>
  );
}
