import type { ROIRect } from './ROITypes';

/** Tareas de inferencia expuestas por el registry de modelos del backend */
export type ModelTask = 'localization' | 'classification' | 'ocr' | 'anomaly';

/** Modelo tal como lo devuelve GET /models (estado real del registry, no un mock) */
export interface ApiModel {
  readonly id: string;
  readonly task: ModelTask;
  readonly backend: string;
  readonly default: boolean;
  readonly enabled: boolean;
  /** false mientras el backend/dependencia (ultralytics, torchvision, paddleocr...) no esté instalado */
  readonly available: boolean;
  /** true una vez que se cargó en memoria (carga lazy en el primer uso) */
  readonly loaded: boolean;
  readonly config?: Record<string, unknown>;
}

export interface BoundingBoxXYXY {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** ROI en formato de request: "x,y,width,height" */
export type InferenceRoi = ROIRect;

/** Bounding box de una detección YOLO */
export interface LocalizationDetection {
  classId: number;
  className?: string;
  confidence: number;
  bbox: BoundingBoxXYXY;
}

export interface LocalizationResult {
  task: 'localization';
  modelId: string;
  roi: [number, number, number, number] | null;
  detections: LocalizationDetection[];
}

/** Una de las top-K predicciones de clasificación */
export interface ClassificationPrediction {
  classId: number;
  label?: string;
  confidence: number;
}

export interface ClassificationResult {
  task: 'classification';
  modelId: string;
  roi: [number, number, number, number] | null;
  predictions: ClassificationPrediction[];
}

/** Línea de texto reconocida por PaddleOCR */
export interface OcrTextResult {
  text: string;
  confidence: number;
  bbox?: BoundingBoxXYXY;
}

export interface OcrResult {
  task: 'ocr';
  modelId: string;
  roi: [number, number, number, number] | null;
  results: OcrTextResult[];
}

/** Región anómala detectada al comparar contra la imagen de referencia */
export interface AnomalyRegion {
  score: number;
  area: number;
  bbox: BoundingBoxXYXY;
}

export interface AnomalyResult {
  task: 'anomaly';
  modelId: string;
  roi: [number, number, number, number] | null;
  anomalyScore: number;
  regions: AnomalyRegion[];
}

export type InferenceResult = LocalizationResult | ClassificationResult | OcrResult | AnomalyResult;

/** Cuerpo de error de negocio (4xx/5xx): detail siempre es string */
export interface InferenceApiErrorBody {
  detail: string;
}

/** Cuerpo de error de validación (422): detail es un array de errores de FastAPI/Pydantic */
export interface InferenceValidationErrorBody {
  detail: Array<{ type: string; loc: (string | number)[]; msg?: string }>;
}
