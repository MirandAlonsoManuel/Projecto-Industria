/**
 * T-036: notificación de errores de REST (React Query) y de la inferencia manual.
 *
 * Reglas para no saturar al usuario:
 *  - Servidor caído (error de red): UN solo aviso "Servidor no disponible",
 *    venga de la consulta que venga; se cierra solo al volver cualquier respuesta.
 *  - Error HTTP de una consulta: un aviso por consulta, con "Reintentar", y solo
 *    si no hay datos en caché que mostrar (si los hay, la pantalla sigue útil).
 *  - Cada consulta decide con `meta.notify`:
 *      'all' (por defecto) | 'network-only' (p. ej. /signal) | 'none'
 */
import { isApiError } from './httpClient';
import { useToastStore } from '../store/toastStore';

export type QueryNotifyMode = 'all' | 'network-only' | 'none';

// `type` (no interface): React Query exige que meta sea asignable a Record<string, unknown>
export type QueryErrorMeta = {
  notify?: QueryNotifyMode;
  /** Título del aviso para esta consulta, p. ej. "No se pudo cargar la lista de modelos" */
  errorTitle?: string;
};

/** Datos mínimos de una consulta que se necesitan para notificar */
export interface QueryLike {
  queryHash: string;
  meta?: Record<string, unknown>;
  state: { data: unknown };
}

export const SERVER_TOAST_KEY = 'server';
export const MANUAL_INFERENCE_TOAST_KEY = 'inference-manual';
export const queryToastKey = (queryHash: string) => `query:${queryHash}`;

export function isNetworkError(error: unknown): boolean {
  return isApiError(error) && error.kind === 'network';
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

/** Llamar cuando una consulta falla (desde QueryCache.onError). */
export function notifyQueryError(error: unknown, query: QueryLike, retry: () => void): void {
  const meta = (query.meta ?? {}) as QueryErrorMeta;
  const mode = meta.notify ?? 'all';
  if (mode === 'none') return;

  const toasts = useToastStore.getState();

  if (isNetworkError(error)) {
    toasts.show({
      key: SERVER_TOAST_KEY,
      severity: 'warning',
      title: 'Servidor no disponible',
      message: 'No se pudo conectar con el servidor. Se reintentará automáticamente.',
    });
    return;
  }

  if (mode === 'network-only') return;
  // Con datos en caché la pantalla sigue funcionando: no se interrumpe al usuario
  if (query.state.data !== undefined) return;

  toasts.show({
    key: queryToastKey(query.queryHash),
    severity: 'error',
    title: meta.errorTitle ?? 'No se pudieron cargar los datos',
    message: errorMessage(error),
    actionLabel: 'Reintentar',
    onAction: () => {
      toasts.dismissByKey(queryToastKey(query.queryHash));
      retry();
    },
  });
}

/** Llamar cuando una consulta responde bien (desde QueryCache.onSuccess). */
export function notifyQuerySuccess(query: Pick<QueryLike, 'queryHash'>): void {
  const toasts = useToastStore.getState();
  // Cualquier respuesta demuestra que el servidor volvió
  toasts.dismissByKey(SERVER_TOAST_KEY);
  toasts.dismissByKey(queryToastKey(query.queryHash));
}

/** Error al ejecutar una inferencia manual (panel de inferencia). */
export function notifyManualInferenceError(message: string, retry: () => void): void {
  useToastStore.getState().show({
    key: MANUAL_INFERENCE_TOAST_KEY,
    severity: 'error',
    title: 'La inferencia falló',
    message,
    actionLabel: 'Reintentar',
    onAction: () => {
      useToastStore.getState().dismissByKey(MANUAL_INFERENCE_TOAST_KEY);
      retry();
    },
  });
}

/** La inferencia manual volvió a funcionar (o se inició otra): se quita el aviso. */
export function clearManualInferenceError(): void {
  useToastStore.getState().dismissByKey(MANUAL_INFERENCE_TOAST_KEY);
}
