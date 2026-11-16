/**
 * HU-12: traduce los mensajes y cierres del WebSocket de stream a un estado de sesión
 * (connecting / active / stopped / disconnected / error).
 *
 * Funciona con el backend actual (solo `connected`, `error`, `description`) y con el
 * contrato de HU-12 (`type`, `state`, `code`, `recoverable`): si el backend manda un
 * campo, se respeta; si no, se deduce de las tablas de abajo.
 */
import type {
  RawStreamControlMessage,
  StreamSessionState,
  StreamSessionStatus,
} from '../types';

/** Código de cierre que usa el cliente cuando el watchdog detecta un stream congelado. */
export const STREAM_FROZEN_CLOSE_CODE = 4000;

/** Errores sin aviso del servidor: se generan en el cliente. */
export const CONNECTION_LOST_CODE = 'CONNECTION_LOST';
export const STREAM_FROZEN_CODE = 'STREAM_FROZEN';

/**
 * Si un error es recuperable (el cliente puede reintentar solo).
 * PROVISIONAL: debe coincidir con lo que defina el backend en HU-12
 * (códigos de CLOSE_CODES en backend/app/services/stream_runner.py).
 * Un código que no esté aquí se trata como no recuperable.
 */
export const ERROR_RECOVERABILITY: Record<string, boolean> = {
  CAMERA_BUSY: true, // otro cliente la usa; puede liberarse
  CAMERA_UNAVAILABLE: true, // la cámara no abrió; puede conectarse después
  CAMERA_NO_FRAMES: true,
  CAMERA_READ_ERROR: true,
  CAMERA_STALLED: true,
  STREAM_ERROR: true,
  STREAM_CLOSED: true,
  [CONNECTION_LOST_CODE]: true,
  [STREAM_FROZEN_CODE]: true,
  CAMERA_MISMATCH: false, // la sesión usa otra cámara: el usuario debe cambiarla
  SERVICE_SHUTTING_DOWN: false,
  SERVICE_SHUTDOWN: false,
};

/** Códigos que no son un error sino un fin de sesión intencional. */
const END_STATE_BY_CODE: Record<string, StreamSessionState> = {
  SESSION_STOPPED: 'stopped', // un operador detuvo la sesión
  SERVICE_SHUTDOWN: 'stopped', // el servidor se apagó
  SERVICE_SHUTTING_DOWN: 'stopped',
  CLIENT_DISCONNECTED: 'disconnected', // un operador expulsó al cliente
};

const KNOWN_STATES: readonly StreamSessionState[] = [
  'connecting',
  'active',
  'stopped',
  'disconnected',
  'error',
];

const FALLBACK_DESCRIPTIONS: Record<string, string> = {
  [CONNECTION_LOST_CODE]: 'Se perdió la conexión con el servidor.',
  [STREAM_FROZEN_CODE]: 'El stream dejó de enviar frames.',
};

export const CONNECTING_STATUS: StreamSessionStatus = {
  state: 'connecting',
  code: null,
  description: null,
  recoverable: true,
};

function isKnownState(value: unknown): value is StreamSessionState {
  return KNOWN_STATES.includes(value as StreamSessionState);
}

export function isRecoverableCode(code: string | null, explicit?: boolean): boolean {
  if (typeof explicit === 'boolean') return explicit;
  if (!code) return false;
  return ERROR_RECOVERABILITY[code] ?? false;
}

/** Estado que corresponde a un código de fin o de error. */
export function statusFromCode(
  code: string | null,
  description: string | null,
  explicitRecoverable?: boolean
): StreamSessionStatus {
  const endState = code ? END_STATE_BY_CODE[code] : undefined;
  if (endState) {
    // Un fin intencional no se reintenta solo, aunque el servicio vuelva luego.
    return { state: endState, code, description, recoverable: explicitRecoverable ?? false };
  }
  return {
    state: 'error',
    code,
    description: description ?? (code ? FALLBACK_DESCRIPTIONS[code] ?? null : null),
    recoverable: isRecoverableCode(code, explicitRecoverable),
  };
}

/**
 * Traduce un mensaje de texto del WebSocket. Devuelve null si no es un mensaje
 * de control reconocible (JSON inválido o sin campos útiles).
 */
export function parseControlMessage(data: string): StreamSessionStatus | null {
  let msg: RawStreamControlMessage;
  try {
    const parsed: unknown = JSON.parse(data);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    msg = parsed as RawStreamControlMessage;
  } catch {
    return null;
  }

  const code = msg.code ?? msg.error ?? null;
  const description = msg.description ?? null;

  // Contrato HU-12: el mensaje declara su tipo y su estado.
  // (Sin `type`, el `state` de hoy es el del gestor de cámara —streaming, running…—
  // y no se mezcla con los estados de la sesión del cliente.)
  if (msg.type !== undefined && isKnownState(msg.state)) {
    if (msg.state === 'active' || msg.state === 'connecting') {
      return { state: msg.state, code: null, description, recoverable: true };
    }
    if (msg.state === 'error') {
      return {
        state: 'error',
        code,
        description,
        recoverable: isRecoverableCode(code, msg.recoverable),
      };
    }
    return { state: msg.state, code, description, recoverable: msg.recoverable ?? false };
  }

  // Backend actual
  if (msg.connected === true) {
    return { state: 'active', code: null, description, recoverable: true };
  }
  if (msg.connected === false || code) {
    return statusFromCode(code, description, msg.recoverable);
  }
  return null;
}

/**
 * Estado final al cerrarse el socket. Si el servidor ya avisó por qué cerraba
 * (stopped, disconnected o error), se conserva ese aviso; si cerró sin aviso,
 * se trata como pérdida de conexión, que sí se reintenta.
 */
export function statusFromClose(
  closeCode: number,
  last: StreamSessionStatus | null
): StreamSessionStatus {
  if (last && last.state !== 'active' && last.state !== 'connecting') return last;
  const code = closeCode === STREAM_FROZEN_CLOSE_CODE ? STREAM_FROZEN_CODE : CONNECTION_LOST_CODE;
  return statusFromCode(code, null);
}

/** Reconectar solo ante errores recuperables; nunca tras un fin intencional. */
export function shouldReconnect(status: StreamSessionStatus): boolean {
  return status.state === 'error' && status.recoverable;
}
