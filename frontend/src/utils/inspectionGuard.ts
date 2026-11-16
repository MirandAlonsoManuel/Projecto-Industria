import type { ApiModel } from '../types';

export interface InspectionStartCheck {
  ok: boolean;
  /** Texto para mostrar al usuario cuando ok es false */
  message: string | null;
}

/**
 * HU-11: el WebSocket de inferencia en vivo (/ws/inference-stream) solo atiende modelos
 * de detección (task 'localization'). Decide si se puede iniciar el análisis con el modelo activo.
 */
export function checkLiveInferenceStart(models: ApiModel[], modelId: string): InspectionStartCheck {
  if (!modelId) {
    return { ok: false, message: 'No hay ningún modelo disponible para iniciar el análisis.' };
  }
  const model = models.find((m) => m.id === modelId);
  if (!model || model.task !== 'localization') {
    return {
      ok: false,
      message: `El análisis en vivo requiere un modelo de detección disponible. Modelo activo: ${modelId}.`,
    };
  }
  return { ok: true, message: null };
}