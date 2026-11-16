/**
 * T-036: catálogo de errores del job de inspección.
 *
 * Traduce un código (del backend vía HU-12, o propio del cliente) a un mensaje
 * para el operador, con su gravedad, si es recuperable y la acción sugerida.
 * Así el mismo error se ve igual en el toast y en el estado de la UI.
 */
import type { ApiModel } from '../types';
import type { WsConnectionStatus } from '../store/inferenceConnectionStore';

export type JobErrorSeverity = 'warning' | 'error';

/** Qué puede hacer el operador para resolverlo */
export type JobErrorAction = 'retry' | 'select_model' | 'check_roi' | 'check_camera' | 'wait';

export interface JobErrorInfo {
  code: string;
  title: string;
  message: string;
  severity: JobErrorSeverity;
  /** true = la inspección puede seguir (se pausa y se reintenta sola) */
  recoverable: boolean;
  action: JobErrorAction;
  /** Detalle técnico del backend, si lo hubo */
  detail: string | null;
}

/** Errores que detecta el propio cliente antes o durante la inspección */
export const CLIENT_JOB_ERRORS = {
  NO_MODEL: 'NO_MODEL',
  MODEL_UNAVAILABLE: 'MODEL_UNAVAILABLE',
  MODEL_NOT_LIVE: 'MODEL_NOT_LIVE',
  CAMERA_NOT_READY: 'CAMERA_NOT_READY',
  CAMERA_DISCONNECTED: 'CAMERA_DISCONNECTED',
  /** Deducido de la descripción de STREAM_ERROR hasta que el backend mande un código propio */
  INVALID_ROI: 'INVALID_ROI',
} as const;

type CatalogEntry = Omit<JobErrorInfo, 'code' | 'detail'>;

const CATALOG: Record<string, CatalogEntry> = {
  // ── Validaciones del cliente al iniciar ──────────────────────────────────
  NO_MODEL: {
    title: 'Selecciona un modelo',
    message: 'Elige un modelo antes de iniciar la inspección.',
    severity: 'warning',
    recoverable: false,
    action: 'select_model',
  },
  MODEL_UNAVAILABLE: {
    title: 'Modelo no disponible',
    message: 'El modelo seleccionado no está instalado o está deshabilitado en el servidor.',
    severity: 'warning',
    recoverable: false,
    action: 'select_model',
  },
  MODEL_NOT_LIVE: {
    title: 'Modelo no compatible',
    message: 'La inspección en vivo solo funciona con modelos de detección (localización).',
    severity: 'warning',
    recoverable: false,
    action: 'select_model',
  },
  CAMERA_NOT_READY: {
    title: 'Cámara conectándose',
    message: 'Espera a que la cámara termine de conectarse para iniciar la inspección.',
    severity: 'warning',
    recoverable: true,
    action: 'wait',
  },
  CAMERA_DISCONNECTED: {
    title: 'Cámara sin conexión',
    message: 'No hay conexión con la cámara. Revísala e inténtalo de nuevo.',
    severity: 'warning',
    recoverable: false,
    action: 'check_camera',
  },
  INVALID_ROI: {
    title: 'ROI inválido',
    message: 'La zona de interés está fuera de la imagen. Ajústala o desactívala.',
    severity: 'error',
    recoverable: false,
    action: 'check_roi',
  },

  // ── Errores del stream (códigos del backend, ver CLOSE_CODES) ────────────
  CAMERA_BUSY: {
    title: 'Cámara ocupada',
    message: 'Otro cliente está usando la cámara. Se reintentará cuando se libere.',
    severity: 'warning',
    recoverable: true,
    action: 'wait',
  },
  CAMERA_UNAVAILABLE: {
    title: 'Cámara no disponible',
    message: 'No se pudo abrir la cámara. Se seguirá intentando.',
    severity: 'warning',
    recoverable: true,
    action: 'check_camera',
  },
  CAMERA_NO_FRAMES: {
    title: 'La cámara no envía imagen',
    message: 'La cámara dejó de enviar frames. Se seguirá intentando.',
    severity: 'warning',
    recoverable: true,
    action: 'check_camera',
  },
  CAMERA_READ_ERROR: {
    title: 'Error de lectura de la cámara',
    message: 'Falló la lectura de la cámara. Se seguirá intentando.',
    severity: 'warning',
    recoverable: true,
    action: 'check_camera',
  },
  CAMERA_STALLED: {
    title: 'Cámara estancada',
    message: 'La cámara se congeló. Se seguirá intentando.',
    severity: 'warning',
    recoverable: true,
    action: 'check_camera',
  },
  CAMERA_MISMATCH: {
    title: 'Cámara distinta',
    message: 'El servidor está usando otra cámara. Cambia a esa cámara o detén su sesión.',
    severity: 'error',
    recoverable: false,
    action: 'check_camera',
  },
  STREAM_ERROR: {
    title: 'Error en la inferencia',
    message: 'El servidor no pudo procesar la imagen. Se seguirá intentando.',
    severity: 'warning',
    recoverable: true,
    action: 'retry',
  },
  STREAM_CLOSED: {
    title: 'Stream cerrado',
    message: 'El servidor cerró el stream. Se seguirá intentando.',
    severity: 'warning',
    recoverable: true,
    action: 'retry',
  },
  CONNECTION_LOST: {
    title: 'Conexión perdida',
    message: 'Se perdió la conexión con el servidor. Reconectando…',
    severity: 'warning',
    recoverable: true,
    action: 'wait',
  },
  STREAM_FROZEN: {
    title: 'Stream congelado',
    message: 'Dejaron de llegar imágenes. Reconectando…',
    severity: 'warning',
    recoverable: true,
    action: 'wait',
  },
  SESSION_STOPPED: {
    title: 'Sesión detenida',
    message: 'Un operador detuvo la sesión de la cámara.',
    severity: 'warning',
    recoverable: false,
    action: 'retry',
  },
  CLIENT_DISCONNECTED: {
    title: 'Desconectado por un operador',
    message: 'Un operador desconectó este cliente de la cámara.',
    severity: 'warning',
    recoverable: false,
    action: 'retry',
  },
  SERVICE_SHUTTING_DOWN: {
    title: 'Servidor apagándose',
    message: 'El servidor se está apagando. Inténtalo cuando vuelva a estar disponible.',
    severity: 'error',
    recoverable: false,
    action: 'retry',
  },
  SERVICE_SHUTDOWN: {
    title: 'Servidor apagado',
    message: 'El servidor se apagó. Inténtalo cuando vuelva a estar disponible.',
    severity: 'error',
    recoverable: false,
    action: 'retry',
  },
};

const UNKNOWN: CatalogEntry = {
  title: 'Error en la inspección',
  message: 'Ocurrió un error inesperado.',
  severity: 'error',
  recoverable: false,
  action: 'retry',
};

/** Texto del botón para cada acción sugerida */
export const ACTION_LABELS: Record<JobErrorAction, string> = {
  retry: 'Reintentar',
  select_model: 'Cambiar modelo',
  check_roi: 'Revisar ROI',
  check_camera: 'Revisar cámara',
  wait: 'Esperar',
};

/**
 * Código efectivo: el backend manda hoy un ROI inválido como STREAM_ERROR genérico;
 * se reconoce por su descripción para no reintentar algo que siempre va a fallar.
 * TEMPORAL: quitar cuando el backend mande INVALID_ROI.
 */
function refineCode(code: string | null, detail: string | null): string | null {
  if (code === 'STREAM_ERROR' && detail && /\bROI\b/i.test(detail)) {
    return CLIENT_JOB_ERRORS.INVALID_ROI;
  }
  return code;
}

/** Información completa de un error del job a partir de su código. */
export function describeJobError(code: string | null, detail: string | null = null): JobErrorInfo {
  const effective = refineCode(code, detail);
  const entry = (effective && CATALOG[effective]) || UNKNOWN;
  return {
    code: effective ?? 'UNKNOWN',
    ...entry,
    // Un error desconocido sin texto propio muestra el del backend
    message: entry === UNKNOWN && detail ? detail : entry.message,
    detail,
  };
}

export interface JobStartContext {
  modelId: string;
  models: readonly ApiModel[];
  connectionStatus: WsConnectionStatus;
}

/**
 * Valida que la inspección pueda arrancar. Devuelve el primer problema
 * encontrado, o null si todo está bien.
 */
export function validateJobStart({
  modelId,
  models,
  connectionStatus,
}: JobStartContext): JobErrorInfo | null {
  if (!modelId) return describeJobError(CLIENT_JOB_ERRORS.NO_MODEL);
  const model = models.find((m) => m.id === modelId);
  if (!model) return describeJobError(CLIENT_JOB_ERRORS.NO_MODEL);
  if (!model.available || !model.enabled) {
    return describeJobError(CLIENT_JOB_ERRORS.MODEL_UNAVAILABLE);
  }
  if (model.task !== 'localization') return describeJobError(CLIENT_JOB_ERRORS.MODEL_NOT_LIVE);
  if (connectionStatus === 'reconnecting') {
    return describeJobError(CLIENT_JOB_ERRORS.CAMERA_NOT_READY);
  }
  if (connectionStatus !== 'connected') {
    return describeJobError(CLIENT_JOB_ERRORS.CAMERA_DISCONNECTED);
  }
  return null;
}
