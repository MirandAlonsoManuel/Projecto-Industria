// Dibujo de las detecciones del modelo sobre el canvas de <DetectionCanvas />.
// Lo dispara useCameraStream en cada frame nuevo (y al redimensionar), para que
// las cajas correspondan siempre al frame que se ve.
import type { LocalizationDetection } from '../types';
import { bboxToCanvas, computeBBoxTransform, computeContainFit, type Size } from './bboxTransform';
import type { AccuracyLevel } from '../store/detectionColorStore';
import { colorForClass, labelTextColor, colorForConfidence } from './detectionColors';

const LABEL_HEIGHT = 16;
const LINE_WIDTH = 2;

/**
 * Ajusta el tamaño interno del canvas al tamaño en pantalla × devicePixelRatio,
 * para que líneas y texto se vean nítidos en pantallas HiDPI. Después se dibuja
 * en píxeles CSS gracias a setTransform.
 */
function prepareCanvas(canvas: HTMLCanvasElement, display: Size): CanvasRenderingContext2D | null {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(display.width * dpr);
  const h = Math.round(display.height * dpr);
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;

  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

/** Limpia la capa (sin detecciones, sin frame o al desconectar). */
export function clearDetections(canvas: HTMLCanvasElement): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

/**
 * Redibuja la capa completa con las detecciones de UN frame. Siempre limpia antes,
 * así nunca quedan cajas de frames anteriores.
 * @param frame      Tamaño real del frame decodificado
 * @param display    Tamaño del canvas en pantalla (px CSS)
 * @param sourceSize Espacio de coordenadas de las bbox, si no son píxeles del frame
 */
export function redrawDetections(
  canvas: HTMLCanvasElement,
  detections: LocalizationDetection[],
  frame: Size,
  display: Size,
  sourceSize?: Size | null,
  accuracyLevels?: AccuracyLevel[]
): void {
  if (display.width <= 0 || display.height <= 0) return;
  const ctx = prepareCanvas(canvas, display);
  if (!ctx || detections.length === 0) return;

  const fit = computeContainFit(display, frame);
  const transform = computeBBoxTransform(fit, frame, sourceSize);

  ctx.font = 'bold 11px sans-serif';
  ctx.lineWidth = LINE_WIDTH;

  for (const det of detections) {
    const rect = bboxToCanvas(det.bbox, transform, fit);
    if (!rect) continue;

    const color = accuracyLevels
      ? colorForConfidence(det.confidence, accuracyLevels)
      : colorForClass(det.classId);

    // Caja de la detección
    ctx.strokeStyle = color;
    ctx.strokeRect(rect.x, rect.y, rect.width, rect.height);

    // Etiqueta: clase + % de confianza
    const label = `${det.className ?? `clase ${det.classId}`} ${Math.round(det.confidence * 100)}%`;
    const tw = ctx.measureText(label).width + 6;
    // Si no cabe encima de la caja, se dibuja por dentro; nunca se sale por la derecha
    const ly = rect.y - LABEL_HEIGHT >= fit.dy ? rect.y - LABEL_HEIGHT : rect.y;
    const lx = Math.max(fit.dx, Math.min(rect.x, fit.dx + fit.dw - tw));
    ctx.fillStyle = color;
    ctx.fillRect(lx, ly, tw, LABEL_HEIGHT);
    ctx.fillStyle = labelTextColor(color);
    ctx.fillText(label, lx + 3, ly + LABEL_HEIGHT - 4);
  }
}
