/**
 * T-035: estado de la conexión WebSocket del stream (conectado / desconectado /
 * reconectando / error), global para toda la app.
 *
 * Sin polling REST: el estado se deriva solo de los eventos del socket
 * (onopen / onclose / onerror), que publican los hooks useCameraStream y
 * useInferenceStream. Los componentes solo leen.
 *
 * Cada ejecución de un hook se identifica con un `owner`. El último que empieza
 * a conectar es el dueño y los eventos de cualquier otro (p. ej. un socket viejo
 * que cierra después de cambiar de modo) se ignoran.
 */
import { create } from 'zustand';
import type { CameraConnectionStatus, StreamSessionStatus } from '../types';

export type WsConnectionStatus = 'connected' | 'disconnected' | 'reconnecting' | 'error';
export type WsEndpoint = 'stream' | 'inference';

export interface WsConnectionError {
  code: string | null;
  description: string | null;
}

export interface WsConnectionState {
  status: WsConnectionStatus;
  /** Ejecución del hook dueña del estado; null = ningún socket activo */
  owner: string | null;
  /** Endpoint del socket dueño: /ws/stream o /ws/inference-stream */
  endpoint: WsEndpoint | null;
  /** Intentos de conexión desde el último éxito (0 = primer intento) */
  attempt: number;
  lastError: WsConnectionError | null;
  /** Momento (ms) del último cambio de estado */
  changedAt: number;
}

export type WsConnectionEvent =
  | { type: 'connecting'; owner: string; endpoint: WsEndpoint }
  | { type: 'opened'; owner: string }
  | { type: 'errored'; owner: string; message: string }
  | {
      type: 'closed';
      owner: string;
      /** Estado final de la sesión (HU-12): dice si fue fin intencional o error */
      session: StreamSessionStatus;
      /** El hook va a reintentar por sí solo */
      willReconnect: boolean;
    }
  | { type: 'released'; owner: string };

export const INITIAL_CONNECTION_STATE: WsConnectionState = {
  status: 'disconnected',
  owner: null,
  endpoint: null,
  attempt: 0,
  lastError: null,
  changedAt: 0,
};

/** Transición pura: estado actual + evento del socket → estado nuevo. */
export function reduceConnection(
  state: WsConnectionState,
  event: WsConnectionEvent,
  now: number
): WsConnectionState {
  if (event.type === 'connecting') {
    const sameOwner = state.owner === event.owner;
    return {
      ...state,
      // El primer intento también se muestra como "reconnecting" (Conectando…)
      status: 'reconnecting',
      owner: event.owner,
      endpoint: event.endpoint,
      attempt: sameOwner ? state.attempt + 1 : 0,
      lastError: sameOwner ? state.lastError : null,
      changedAt: now,
    };
  }

  // Eventos de un socket que ya no es el dueño: se ignoran
  if (event.owner !== state.owner) return state;

  switch (event.type) {
    case 'opened':
      return { ...state, status: 'connected', attempt: 0, lastError: null, changedAt: now };

    case 'errored':
      // El navegador siempre manda onclose justo después; ese decide el estado
      return { ...state, lastError: { code: null, description: event.message } };

    case 'closed': {
      const { session, willReconnect } = event;
      const lastError: WsConnectionError | null =
        session.code || session.description
          ? { code: session.code, description: session.description }
          : state.lastError;
      let status: WsConnectionStatus;
      if (willReconnect) status = 'reconnecting';
      else if (session.state === 'error') status = 'error'; // no recuperable o tope de 2 min
      else status = 'disconnected'; // fin intencional: sesión detenida o cliente expulsado
      return { ...state, status, lastError, changedAt: now };
    }

    case 'released':
      return { ...INITIAL_CONNECTION_STATE, changedAt: now };
  }
}

interface WsConnectionActions {
  socketConnecting: (owner: string, endpoint: WsEndpoint) => void;
  socketOpened: (owner: string) => void;
  socketErrored: (owner: string, message: string) => void;
  socketClosed: (owner: string, session: StreamSessionStatus, willReconnect: boolean) => void;
  socketReleased: (owner: string) => void;
}

export const useInferenceConnectionStore = create<WsConnectionState & WsConnectionActions>(
  (set) => {
    const dispatch = (event: WsConnectionEvent) =>
      set((state) => reduceConnection(state, event, Date.now()));
    return {
      ...INITIAL_CONNECTION_STATE,
      socketConnecting: (owner, endpoint) => dispatch({ type: 'connecting', owner, endpoint }),
      socketOpened: (owner) => dispatch({ type: 'opened', owner }),
      socketErrored: (owner, message) => dispatch({ type: 'errored', owner, message }),
      socketClosed: (owner, session, willReconnect) =>
        dispatch({ type: 'closed', owner, session, willReconnect }),
      socketReleased: (owner) => dispatch({ type: 'released', owner }),
    };
  }
);

let ownerSeq = 0;
/** Identificador único para cada ejecución de un hook de stream. */
export function nextConnectionOwner(prefix: string): string {
  ownerSeq += 1;
  return `${prefix}-${ownerSeq}`;
}

/** Traduce el estado del store a lo que muestra ConnectionStatusBadge. */
export function connectionBadge(state: Pick<WsConnectionState, 'status' | 'attempt' | 'lastError'>): {
  status: CameraConnectionStatus;
  label: string;
  detail: string | null;
} {
  switch (state.status) {
    case 'connected':
      return { status: 'connected', label: 'Conectado', detail: null };
    case 'reconnecting':
      return {
        status: 'connecting',
        label: state.attempt === 0 ? 'Conectando...' : 'Reconectando...',
        detail: state.lastError?.description ?? null,
      };
    case 'error':
      return {
        status: 'error',
        label: 'Error de conexión',
        detail: state.lastError?.description ?? null,
      };
    case 'disconnected':
      return {
        status: 'disconnected',
        label: 'Sin conexión',
        detail: state.lastError?.description ?? null,
      };
  }
}
