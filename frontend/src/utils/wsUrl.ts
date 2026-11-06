import { WS_URL } from '../config';
import { roiToBackendParams, type NaturalSize, type NormalizedROI } from './roiUtils';

const STREAM_WS_URL = `${WS_URL}/ws/stream`;
const INFERENCE_WS_URL = `${WS_URL}/ws/inference-stream`;

export interface CameraStreamOptions {
  /** 'inference' abre /ws/inference-stream y cada frame trae sus detecciones */
  mode?: 'stream' | 'inference';
  modelId?: string;
  conf?: number;
  iou?: number;
  inferEveryNFrames?: number;
  /** ROI normalizado (0-1). Se convierte a píxeles con el tamaño REAL del frame. */
  roi?: NormalizedROI | null;
}

/**
 * HU-11: arma la URL del WebSocket. Iniciar el análisis = conectar /ws/inference-stream con
 * estos parámetros; detenerlo = volver a /ws/stream (el efecto del hook cierra el socket anterior).
 *
 * El backend espera el ROI en píxeles del frame original y rechaza los que se salen de él,
 * por eso se necesita frameSize (el tamaño real del frame). Si aún no se conoce, el ROI se omite.
 */
export function buildWsUrl(
  cameraId: string,
  options: CameraStreamOptions,
  frameSize: NaturalSize | null
): string {
  const params = new URLSearchParams();
  params.set('camera_id', cameraId);

  if (options.mode === 'inference') {
    if (options.modelId) params.set('model_id', options.modelId);
    if (options.conf !== undefined) params.set('conf', String(options.conf));
    if (options.iou !== undefined) params.set('iou', String(options.iou));
    if (options.inferEveryNFrames !== undefined) {
      params.set('infer_every_n_frames', String(options.inferEveryNFrames));
    }
    if (options.roi && frameSize) {
      const { x1, y1, x2, y2 } = roiToBackendParams(options.roi, frameSize);
      params.set('x1', String(x1));
      params.set('y1', String(y1));
      params.set('x2', String(x2));
      params.set('y2', String(y2));
    }
  }

  const base = options.mode === 'inference' ? INFERENCE_WS_URL : STREAM_WS_URL;
  return `${base}?${params.toString()}`;
}