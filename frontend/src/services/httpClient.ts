import axios from 'axios';
import { API_URL } from '../config';

/** Instancia axios compartida por todos los servicios que hablan con el backend. */
export const api = axios.create({
  baseURL: API_URL,
  timeout: 5000,
});

/**
 * T-036: error del backend con su tipo, para que la UI sepa cómo notificarlo.
 * - network: no hubo respuesta (servidor caído, sin red, CORS, timeout)
 * - http:    el servidor respondió con un código de error
 *
 * Conserva `response` (status + body) igual que un error de axios, así que el
 * código que ya leía `err.response` (p. ej. parseInferenceError) sigue funcionando.
 */
export class ApiError extends Error {
  readonly kind: 'network' | 'http';
  readonly status: number | null;
  readonly response?: { status: number; data: unknown };

  constructor(
    message: string,
    kind: 'network' | 'http',
    response?: { status: number; data: unknown }
  ) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = response?.status ?? null;
    this.response = response;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export const NETWORK_ERROR_MESSAGE = 'No se pudo conectar con el servidor. Comprueba tu conexión.';

/** Mensaje legible para un código HTTP; null si no hay uno genérico. */
function httpMessage(status: number, data: unknown): string {
  if (status === 401) return 'No autorizado. Por favor inicia sesión de nuevo.';
  if (status === 403) return 'Acceso denegado.';
  if (status === 404) return 'El recurso solicitado no existe.';
  if (status >= 500) return 'Error interno del servidor. Inténtalo más tarde.';
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return 'La solicitud no es válida.';
}

/**
 * T-24 / T-036: normaliza cualquier error de axios a un ApiError con mensaje en
 * español. Errores que no son de axios se devuelven tal cual.
 */
export function normalizeApiError(error: unknown): unknown {
  if (!axios.isAxiosError(error)) return error;
  if (!error.response) return new ApiError(NETWORK_ERROR_MESSAGE, 'network');
  const { status, data } = error.response;
  return new ApiError(httpMessage(status, data), 'http', { status, data });
}

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(normalizeApiError(error))
);
