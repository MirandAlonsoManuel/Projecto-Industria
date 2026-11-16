import { describe, expect, it } from 'vitest';
import { ACTION_LABELS, describeJobError, validateJobStart } from './jobErrors';
import { ERROR_RECOVERABILITY } from './streamSession';
import type { ApiModel } from '../types';

const model = (over: Partial<ApiModel> = {}): ApiModel => ({
  id: 'yolo',
  task: 'localization',
  backend: 'ultralytics',
  default: true,
  enabled: true,
  available: true,
  loaded: false,
  ...over,
});

describe('describeJobError (T-036)', () => {
  it('cada código del backend tiene mensaje propio y acción con texto', () => {
    for (const code of [...Object.keys(ERROR_RECOVERABILITY), 'SESSION_STOPPED', 'CLIENT_DISCONNECTED']) {
      const info = describeJobError(code);
      expect(info.code, code).toBe(code);
      expect(info.title, code).not.toBe('Error en la inspección');
      expect(info.message, code).toBeTruthy();
      expect(ACTION_LABELS[info.action], code).toBeTruthy();
    }
  });

  it('coincide con la tabla de recuperables del stream (HU-12)', () => {
    for (const [code, recoverable] of Object.entries(ERROR_RECOVERABILITY)) {
      expect(describeJobError(code).recoverable, code).toBe(recoverable);
    }
  });

  it('un STREAM_ERROR por ROI se trata como INVALID_ROI no recuperable', () => {
    const info = describeJobError('STREAM_ERROR', 'ROI está fuera de los límites de la imagen.');
    expect(info).toMatchObject({ code: 'INVALID_ROI', recoverable: false, action: 'check_roi' });
    expect(info.detail).toContain('ROI');
  });

  it('un STREAM_ERROR de otro tipo sigue siendo recuperable', () => {
    expect(describeJobError('STREAM_ERROR', 'modelo no disponible')).toMatchObject({
      code: 'STREAM_ERROR',
      recoverable: true,
    });
  });

  it('un código desconocido usa la descripción del backend y no se reintenta', () => {
    expect(describeJobError('ALGO_NUEVO', 'detalle del servidor')).toMatchObject({
      code: 'ALGO_NUEVO',
      message: 'detalle del servidor',
      severity: 'error',
      recoverable: false,
    });
  });
});

describe('validateJobStart (T-036)', () => {
  const ok = { modelId: 'yolo', models: [model()], connectionStatus: 'connected' as const };

  it('todo correcto → null', () => {
    expect(validateJobStart(ok)).toBeNull();
  });

  it.each([
    ['sin modelo', { modelId: '' }, 'NO_MODEL'],
    ['modelo inexistente', { modelId: 'otro' }, 'NO_MODEL'],
    ['modelo no instalado', { models: [model({ available: false })] }, 'MODEL_UNAVAILABLE'],
    ['modelo deshabilitado', { models: [model({ enabled: false })] }, 'MODEL_UNAVAILABLE'],
    ['modelo de clasificación', { models: [model({ task: 'classification' })] }, 'MODEL_NOT_LIVE'],
    ['cámara conectándose', { connectionStatus: 'reconnecting' as const }, 'CAMERA_NOT_READY'],
    ['cámara desconectada', { connectionStatus: 'disconnected' as const }, 'CAMERA_DISCONNECTED'],
    ['cámara con error', { connectionStatus: 'error' as const }, 'CAMERA_DISCONNECTED'],
  ])('%s → %s', (_, over, code) => {
    expect(validateJobStart({ ...ok, ...over })?.code).toBe(code);
  });
});
