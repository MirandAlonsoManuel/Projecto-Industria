import { describe, expect, it } from 'vitest';
import { buildWsUrl } from './wsUrl';

const parse = (url: string) => new URL(url);
const roi = { x: 0.5, y: 0.25, width: 0.25, height: 0.5 };

describe('buildWsUrl (HU-11)', () => {
  it('detenido: abre /ws/stream solo con camera_id', () => {
    const url = parse(buildWsUrl('0', { mode: 'stream' }, null));
    expect(url.pathname).toBe('/ws/stream');
    expect([...url.searchParams.keys()]).toEqual(['camera_id']);
    expect(url.searchParams.get('camera_id')).toBe('0');
  });

  it('iniciado: abre /ws/inference-stream con camera_id y model_id', () => {
    const url = parse(buildWsUrl('0', { mode: 'inference', modelId: 'yolo11n-localization' }, null));
    expect(url.pathname).toBe('/ws/inference-stream');
    expect(url.searchParams.get('camera_id')).toBe('0');
    expect(url.searchParams.get('model_id')).toBe('yolo11n-localization');
    expect(url.searchParams.has('x1')).toBe(false);
  });

  it('el ROI se convierte con el tamaño REAL del frame, no con uno fijo', () => {
    const small = parse(buildWsUrl('0', { mode: 'inference', modelId: 'm', roi }, { width: 640, height: 480 }));
    expect(Object.fromEntries(['x1', 'y1', 'x2', 'y2'].map((k) => [k, small.searchParams.get(k)]))).toEqual({
      x1: '320',
      y1: '120',
      x2: '480',
      y2: '360',
    });
    const big = parse(buildWsUrl('0', { mode: 'inference', modelId: 'm', roi }, { width: 1920, height: 1080 }));
    expect(big.searchParams.get('x2')).toBe('1440');
  });

  it('el ROI nunca se sale del frame (el backend rechaza los que se salen)', () => {
    const full = { x: 0, y: 0, width: 1, height: 1 };
    const url = parse(buildWsUrl('0', { mode: 'inference', modelId: 'm', roi: full }, { width: 640, height: 480 }));
    expect(Number(url.searchParams.get('x2'))).toBeLessThanOrEqual(640);
    expect(Number(url.searchParams.get('y2'))).toBeLessThanOrEqual(480);
  });

  it('sin tamaño de frame conocido, omite el ROI en lugar de inventar uno', () => {
    const url = parse(buildWsUrl('0', { mode: 'inference', modelId: 'm', roi }, null));
    expect(url.searchParams.has('x1')).toBe(false);
  });

  it('envía conf, iou e infer_every_n_frames solo si se indican', () => {
    const url = parse(
      buildWsUrl('1', { mode: 'inference', modelId: 'm', conf: 0.4, iou: 0.5, inferEveryNFrames: 2 }, null)
    );
    expect(url.searchParams.get('conf')).toBe('0.4');
    expect(url.searchParams.get('iou')).toBe('0.5');
    expect(url.searchParams.get('infer_every_n_frames')).toBe('2');
  });

  it('en modo stream ignora los parámetros de inferencia', () => {
    const url = parse(buildWsUrl('0', { mode: 'stream', modelId: 'm', roi }, { width: 640, height: 480 }));
    expect([...url.searchParams.keys()]).toEqual(['camera_id']);
  });
});