import { describe, expect, it } from 'vitest';
import { nextSnapshot, type Snapshot } from './roiSnapshot';

type Roi = { x1: number; y1: number; x2: number; y2: number };
const roiA: Roi = { x1: 80, y1: 12, x2: 240, y2: 149 };
const roiB: Roi = { x1: 100, y1: 20, x2: 300, y2: 200 };

describe('nextSnapshot', () => {
  it('inactivo: no hay snapshot, aunque el valor cambie', () => {
    expect(nextSnapshot<Roi | null>(null, false, roiA)).toBeNull();
  });

  it('al activarse toma el valor actual', () => {
    expect(nextSnapshot<Roi | null>(null, true, roiA)).toEqual({ value: roiA });
  });

  it('activo: conserva el snapshot aunque el ROI se mueva (no reconecta)', () => {
    const fijo: Snapshot<Roi | null> = { value: roiA };
    expect(nextSnapshot(fijo, true, roiB)).toBe(fijo);
  });

  it('congela también "sin ROI": dibujar uno durante la inspección no cambia la URL', () => {
    const sinRoi: Snapshot<Roi | null> = { value: null };
    expect(nextSnapshot(sinRoi, true, roiB)).toBe(sinRoi);
  });

  it('al desactivarse se libera y el siguiente inicio toma el ROI nuevo', () => {
    const fijo: Snapshot<Roi | null> = { value: roiA };
    const liberado = nextSnapshot(fijo, false, roiB);
    expect(liberado).toBeNull();
    expect(nextSnapshot(liberado, true, roiB)).toEqual({ value: roiB });
  });
});