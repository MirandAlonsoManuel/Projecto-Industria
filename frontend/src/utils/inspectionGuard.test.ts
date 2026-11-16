import { describe, expect, it } from 'vitest';
import type { ApiModel } from '../types';
import { checkLiveInferenceStart } from './inspectionGuard';

const model = (id: string, task: ApiModel['task']): ApiModel => ({
  id,
  task,
  backend: 'test',
  default: false,
  enabled: true,
  available: true,
  loaded: false,
});

describe('checkLiveInferenceStart (HU-11)', () => {
  const models = [model('yolo11n-localization', 'localization'), model('reference-diff-v1', 'anomaly')];

  it('permite iniciar con un modelo de detección', () => {
    expect(checkLiveInferenceStart(models, 'yolo11n-localization')).toEqual({ ok: true, message: null });
  });

  it('rechaza un modelo de anomalías y nombra el modelo activo', () => {
    const result = checkLiveInferenceStart(models, 'reference-diff-v1');
    expect(result.ok).toBe(false);
    expect(result.message).toContain('reference-diff-v1');
  });

  it('rechaza cuando no hay modelo seleccionado', () => {
    expect(checkLiveInferenceStart(models, '').ok).toBe(false);
  });

  it('rechaza un modelo que no está en la lista', () => {
    expect(checkLiveInferenceStart(models, 'no-existe').ok).toBe(false);
  });
});