import { api } from './httpClient';
import type {
  AnomalyRegion,
  AnomalyResult,
  BoundingBoxXYXY,
  ClassificationPrediction,
  ClassificationResult,
  InferenceApiErrorBody,
  InferenceRoi,
  InferenceValidationErrorBody,
  LocalizationDetection,
  LocalizationResult,
  OcrResult,
  OcrTextResult,
} from '../types';

/**
 * Contrato de POST /inference/* verificado contra el backend real corriendo en
 * 127.0.0.1:8000 (no hay OpenAPI, esto se probó con curl):
 * - "image", "model_id" y "reference_image" (anomaly) van en el multipart/form-data.
 * - "roi" va como QUERY PARAM (string "x,y,width,height"), NO como campo del form
 *   (si se manda por form-data el backend lo ignora y responde roi:null).
 * - /inference/anomaly confirmado 200: { task, model_id, roi, anomaly_score, regions }.
 * localization/classification/ocr siguen sin backend instalado (503), así que su shape
 * 200 se infiere por analogía con el envelope de anomaly; ajustar aquí si difiere.
 */

interface RawBoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function mapBBox(raw: RawBoundingBox): BoundingBoxXYXY {
  return { x1: raw.x1, y1: raw.y1, x2: raw.x2, y2: raw.y2 };
}

function buildFormData(image: File, modelId: string): FormData {
  const form = new FormData();
  form.append('image', image);
  form.append('model_id', modelId);
  return form;
}

function roiParams(roi?: InferenceRoi): { params?: { roi: string } } {
  if (!roi) return {};
  return { params: { roi: `${roi.x},${roi.y},${roi.width},${roi.height}` } };
}

/** Traduce los errores documentados (503/400/422) a un mensaje legible en español. */
export function parseInferenceError(err: unknown): string {
  const response = (err as { response?: { status?: number; data?: unknown } })?.response;
  if (!response) return 'No se pudo contactar al servidor de inferencia.';

  const { status, data } = response;
  const body = data as Partial<InferenceApiErrorBody & InferenceValidationErrorBody>;

  if (Array.isArray(body?.detail)) {
    const missing = body.detail
      .map((d) => d.loc?.[d.loc.length - 1])
      .filter(Boolean)
      .join(', ');
    return `Faltan campos requeridos: ${missing || 'desconocido'}.`;
  }

  if (typeof body?.detail === 'string') {
    if (status === 503) return `Modelo no disponible: ${body.detail}`;
    if (status === 400) return `Solicitud inválida: ${body.detail}`;
    return body.detail;
  }

  return 'Ocurrió un error inesperado al ejecutar la inferencia.';
}

interface RawLocalizationResponse {
  task: 'localization';
  model_id: string;
  roi: [number, number, number, number] | null;
  detections: Array<{
    class_id: number;
    class_name?: string;
    confidence: number;
    bbox: RawBoundingBox;
  }>;
}

export function runLocalization(
  image: File,
  modelId: string,
  roi?: InferenceRoi
): Promise<LocalizationResult> {
  return api
    .post<RawLocalizationResponse>(
      '/inference/localization',
      buildFormData(image, modelId),
      roiParams(roi)
    )
    .then((r) => {
      const data = r.data;
      const detections: LocalizationDetection[] = data.detections.map((d) => ({
        classId: d.class_id,
        className: d.class_name,
        confidence: d.confidence,
        bbox: mapBBox(d.bbox),
      }));
      return { task: 'localization', modelId: data.model_id, roi: data.roi, detections };
    });
}

interface RawClassificationResponse {
  task: 'classification';
  model_id: string;
  roi: [number, number, number, number] | null;
  predictions: Array<{ class_id: number; label?: string; confidence: number }>;
}

export function runClassification(
  image: File,
  modelId: string,
  topK = 5,
  roi?: InferenceRoi
): Promise<ClassificationResult> {
  // top_k se manda igual que roi: como query param, no como campo del form
  // (mismo patrón confirmado para roi contra el backend real).
  const params = { ...roiParams(roi).params, top_k: topK };
  return api
    .post<RawClassificationResponse>('/inference/classification', buildFormData(image, modelId), {
      params,
    })
    .then((r) => {
      const data = r.data;
      const predictions: ClassificationPrediction[] = data.predictions.map((p) => ({
        classId: p.class_id,
        label: p.label,
        confidence: p.confidence,
      }));
      return { task: 'classification', modelId: data.model_id, roi: data.roi, predictions };
    });
}

interface RawOcrResponse {
  task: 'ocr';
  model_id: string;
  roi: [number, number, number, number] | null;
  results: Array<{ text: string; confidence: number; bbox?: RawBoundingBox }>;
}

export function runOcr(image: File, modelId: string, roi?: InferenceRoi): Promise<OcrResult> {
  return api
    .post<RawOcrResponse>('/inference/ocr', buildFormData(image, modelId), roiParams(roi))
    .then((r) => {
      const data = r.data;
      const results: OcrTextResult[] = data.results.map((res) => ({
        text: res.text,
        confidence: res.confidence,
        bbox: res.bbox ? mapBBox(res.bbox) : undefined,
      }));
      return { task: 'ocr', modelId: data.model_id, roi: data.roi, results };
    });
}

interface RawAnomalyResponse {
  task: 'anomaly';
  model_id: string;
  roi: [number, number, number, number] | null;
  anomaly_score: number;
  regions: Array<{ score: number; area: number; bbox: RawBoundingBox }>;
}

export function runAnomaly(
  image: File,
  referenceImage: File,
  modelId: string,
  roi?: InferenceRoi
): Promise<AnomalyResult> {
  const form = buildFormData(image, modelId);
  form.append('reference_image', referenceImage);
  return api.post<RawAnomalyResponse>('/inference/anomaly', form, roiParams(roi)).then((r) => {
    const data = r.data;
    const regions: AnomalyRegion[] = data.regions.map((reg) => ({
      score: reg.score,
      area: reg.area,
      bbox: mapBBox(reg.bbox),
    }));
    return {
      task: 'anomaly',
      modelId: data.model_id,
      roi: data.roi,
      anomalyScore: data.anomaly_score,
      regions,
    };
  });
}
