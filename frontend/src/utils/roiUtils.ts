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
  return {
    x1: Math.round(roi.x * naturalSize.width),
    y1: Math.round(roi.y * naturalSize.height),
    x2: Math.round((roi.x + roi.width) * naturalSize.width),
    y2: Math.round((roi.y + roi.height) * naturalSize.height),
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
