import { describe, expect, it } from 'vitest';
import { roiToBackendParams } from './roiUtils';

// ROI de la prueba A de HU-11 (valores del store del navegador)
const roi = { x: 0.12500498, y: 0.00722840, width: 0.34950373, height: 0.38097938 };

describe('roiToBackendParams', () => {
  it('con 1920×1080 reproduce la URL que congelaba la imagen', () => {
    expect(roiToBackendParams(roi, { width: 1920, height: 1080 })).toEqual({
      x1: 240,
      y1: 8,
      x2: 911,
      y2: 419,
    });
  });

  it('con el tamaño real del frame (640×480) el ROI cae dentro del frame', () => {
    const size = { width: 640, height: 480 };
    const p = roiToBackendParams(roi, size);
    expect(p).toEqual({ x1: 80, y1: 3, x2: 304, y2: 186 });
    expect(p.x2).toBeLessThanOrEqual(size.width);
    expect(p.y2).toBeLessThanOrEqual(size.height);
  });

  it('un ROI al borde (0–1) cubre exactamente el frame, sea cual sea su tamaño', () => {
    const full = { x: 0, y: 0, width: 1, height: 1 };
    expect(roiToBackendParams(full, { width: 640, height: 480 })).toEqual({
      x1: 0,
      y1: 0,
      x2: 640,
      y2: 480,
    });
  });
});