import type { StreamSessionStatus } from '../../types';
import type { WebSocketConnectionState } from '../../hooks/useCameraStream';
import { ButtonCommon } from '../CommonComponents';

interface StreamSessionNoticeProps {
  session: StreamSessionStatus;
  connectionState: WebSocketConnectionState;
  onRetry: () => void;
}

const TITLES: Record<StreamSessionStatus['state'], string> = {
  connecting: 'Conectando stream…',
  active: '',
  stopped: 'Sesión detenida',
  disconnected: 'Desconectado',
  error: 'Error en el stream',
};

/**
 * HU-12: muestra el estado de la sesión del stream sobre el visor.
 * No se muestra con la sesión activa. Ofrece "Reintentar" solo cuando el hook
 * dejó de reconectar por sí mismo (fin intencional, error no recuperable o tope de 2 min).
 */
export function StreamSessionNotice({ session, connectionState, onRetry }: StreamSessionNoticeProps) {
  if (session.state === 'active') return null;

  const reconnecting = connectionState === 'reconnecting';
  const canRetry = connectionState === 'disconnected';
  const isError = session.state === 'error';

  const title = reconnecting && session.state === 'connecting' ? 'Reconectando…' : TITLES[session.state];

  return (
    <div
      role={isError ? 'alert' : 'status'}
      data-session-state={session.state}
      className="relative z-10 flex max-w-[80%] flex-col items-center gap-1.5 text-center"
    >
      <p
        className={
          isError ? 'text-sm font-semibold text-[#d64545]' : 'text-[13px] font-medium text-[#6b7280]'
        }
      >
        {title}
      </p>
      {session.description && session.state !== 'connecting' && (
        <p className="text-[12px] text-[#6b7280]">{session.description}</p>
      )}
      {session.code && (
        <p className="text-[11px] font-mono uppercase tracking-wide text-[#9ca3af]">{session.code}</p>
      )}
      {isError && reconnecting && (
        <p className="text-[12px] text-[#6b7280]">Reintentando automáticamente…</p>
      )}
      {canRetry && (
        <ButtonCommon variant="secondary" size="large" onClick={onRetry}>
          Reintentar
        </ButtonCommon>
      )}
    </div>
  );
}
