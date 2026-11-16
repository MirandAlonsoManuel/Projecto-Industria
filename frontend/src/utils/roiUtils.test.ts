import { describe, expect, it } from 'vitest';
import { roiToBackendParams } from './roiUtils';

// El ROI de la captura del error: x 0.257, y 0.096, w 0.358, h 0.711
const roi = { x: 0.257, y: 0.096, width: 0.358, height: 0.711 };

describe('roiToBackendParams', () => {
  it('convierte con el tamaño real del frame y queda dentro de la imagen', () => {
    const px = roiToBackendParams(roi, { width: 640, height: 480 });
    expect(px).toEqual({ x1: 164, y1: 46, x2: 394, y2: 387 });
    expect(px.x2).toBeLessThanOrEqual(640);
    expect(px.y2).toBeLessThanOrEqual(480);
  });

  it('recorta un ROI que se sale por el borde', () => {
    expect(
      roiToBackendParams({ x: -0.1, y: 0.5, width: 1.3, height: 0.6 }, { width: 640, height: 480 })
    ).toEqual({ x1: 0, y1: 240, x2: 640, y2: 480 });
  });
});
