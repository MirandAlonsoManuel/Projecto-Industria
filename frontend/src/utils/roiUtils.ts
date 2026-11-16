/**
 * T-51: ROI coordinate conversion utilities
 */

export interface ROIPixelCoords {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface NormalizedROI {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface NaturalSize {
  width: number;
  height: number;
}

/**
 * Convert a normalized ROI (0-1 range) to absolute pixel coordinates.
 * Returns { x1, y1, x2, y2 } with Math.round applied.
 */
export function roiToBackendParams(roi: NormalizedROI, naturalSize: NaturalSize): ROIPixelCoords {
  // Se recorta a los bordes de la imagen: un ROI pegado al borde (o el redondeo)
  // no debe salirse, porque el backend lo rechaza con "ROI fuera de los límites".
  const clampX = (v: number) => Math.min(Math.max(Math.round(v), 0), naturalSize.width);
  const clampY = (v: number) => Math.min(Math.max(Math.round(v), 0), naturalSize.height);
  return {
    x1: clampX(roi.x * naturalSize.width),
    y1: clampY(roi.y * naturalSize.height),
    x2: clampX((roi.x + roi.width) * naturalSize.width),
    y2: clampY((roi.y + roi.height) * naturalSize.height),
  };
}

/**
 * Build query string fragment like "&x1=100&y1=50&x2=400&y2=300".
 * Returns empty string if naturalSize is null.
 */
export function roiQueryString(
  roi: NormalizedROI | null | undefined,
  naturalSize: NaturalSize | null | undefined
): string {
  if (!roi || !naturalSize) return '';
  const { x1, y1, x2, y2 } = roiToBackendParams(roi, naturalSize);
  return `&x1=${x1}&y1=${y1}&x2=${x2}&y2=${y2}`;
}
