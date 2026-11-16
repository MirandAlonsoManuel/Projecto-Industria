/**
 * HU-12: estados de la sesión de inferencia vistos desde el cliente.
 *
 * El backend actual todavía no emite estos estados: los mensajes que manda hoy
 * se traducen en utils/streamSession.ts. Cuando el backend implemente HU-12,
 * los campos opcionales `type`, `state`, `code` y `recoverable` se usan tal cual.
 */

export type StreamSessionState = 'connecting' | 'active' | 'stopped' | 'disconnected' | 'error';

/** Estado de la sesión listo para la UI. */
export interface StreamSessionStatus {
  state: StreamSessionState;
  /** Código estable del backend (SESSION_STOPPED, CAMERA_BUSY…) o del cliente (CONNECTION_LOST) */
  code: string | null;
  description: string | null;
  /** true = el cliente puede reintentar por sí solo; false = hace falta una acción del usuario */
  recoverable: boolean;
}

/**
 * Mensaje de texto del WebSocket, tal como llega por la red.
 * Hoy: bienvenida `{connected: true, state, client_id, …}` o fin `{connected: false, error, description}`.
 * HU-12 (futuro): agrega `type`, `state` del contrato, `code` y `recoverable`.
 */
export interface RawStreamControlMessage {
  type?: string;
  state?: string;
  connected?: boolean;
  camera_id?: string;
  client_id?: string;
  error?: string | null;
  code?: string | null;
  description?: string | null;
  recoverable?: boolean;
}
