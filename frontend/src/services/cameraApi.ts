import { api } from './httpClient';

export interface SignalResponse {
  connected: boolean;
}

/** Envelope común que usa el backend para /cameras (y potencialmente otras rutas). */
interface ApiEnvelope<T> {
  connected: boolean;
  data: T;
  error: string | null;
  meta?: { total?: number; description?: string } & Record<string, unknown>;
}

/** Cámara USB tal como la expone GET /cameras. */
export interface ApiCamera {
  id: string;
  type?: string;
  sourceUrl?: string;
  status?: string;
}

interface RawApiCamera {
  id: string | number;
  type?: string;
  source_url?: string;
  status?: string;
}

function normalizeCamera(raw: RawApiCamera): ApiCamera {
  return {
    id: String(raw.id),
    type: raw.type,
    sourceUrl: raw.source_url,
    status: raw.status,
  };
}

// /signal es un health check puro del servidor; no acepta ni usa camera_id
export const getSignal = () => api.get<SignalResponse>('/signal').then((r) => r.data);

export interface GetCamerasResult {
  cameras: ApiCamera[];
  /** Total reportado por el backend en meta.total. connected:false no es error, es el estado real. */
  total: number;
  description?: string;
}

export const getCameras = (): Promise<GetCamerasResult> =>
  api.get<ApiEnvelope<RawApiCamera[]>>('/api/cameras').then((r) => {
    const { data, meta } = r.data;
    const cameras = (data ?? []).map(normalizeCamera);
    return {
      cameras,
      total: meta?.total ?? cameras.length,
      description: meta?.description,
    };
  });
