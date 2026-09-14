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
  'inline-flex select-none items-center gap-[7px] rounded-full bg-[#ffffff] px-5 py-1.5 text-xs font-semibold';

const dotBaseClasses = 'h-[9px] w-[9px] shrink-0 rounded-full';

const dotColorClasses: Record<CameraConnectionStatus, string> = {
  connected: 'bg-[#BFDA98] shadow-[#BFDA98]',
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
  const isPulsing =
    status === 'connecting' || status === 'disconnecting';

  return (
    <div className="relative inline-block group">

      {/* Badge */}
      <span
        className={badgeClasses}
        role="status"
        aria-live="polite"
        aria-label={`Estado de cámara: ${meta.label}`}
      >
        <span
          className={`${dotBaseClasses} ${
            dotColorClasses[status]
          } ${isPulsing ? pulsingClass : ''}`}
        />

        {!compact && (
          <span className={labelClasses}>
            {meta.label}

            {cameraName && status === 'connected' && (
              <span className={cameraNameClasses}>
                {' | '}
                {cameraName}
              </span>
            )}
          </span>
        )}
      </span>

      {/* Popover */}
      <div
        className="absolute bottom-full left-1/2 z-50 mb-1.5 w-full -translate-x-1/2 translate-y-2 rounded-2xl bg-white p-3 shadow-lg opacity-0 invisible transition-all duration-200 group-hover:visible group-hover:opacity-100 group-hover:translate-y-0"
      >
        <h5 className="text-center font-bold text-[#393939] text-[12px]">
          Cámara
        </h5>

        <div className="flex justify-between border-b border-gray-200 py-0 text-[10px]">
          <span className='font-semibold'>Cámara actual</span>
          <span className='font-light'>{cameraName ?? 'Sin cámara'}</span>
        </div>

        <div className="flex justify-between border-b border-gray-200 py-0 text-[10px]">
          <span className='font-semibold'>Dirección IP</span>
          <span className='font-light'></span>
        </div>

        <div className="flex justify-between py-0 text-[10px]">
          <span className='font-semibold'>Resolución y FPS</span>
          <span className='font-light'>1920 × 1080, 30</span>
        </div>
      </div>
    </div>
  );
}
