import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MANUAL_INFERENCE_TOAST_KEY,
  SERVER_TOAST_KEY,
  clearManualInferenceError,
  notifyManualInferenceError,
  notifyQueryError,
  notifyQuerySuccess,
  queryToastKey,
  type QueryLike,
} from './errorNotifier';
import { ApiError } from './httpClient';
import { useToastStore } from '../store/toastStore';

const toasts = () => useToastStore.getState().toasts;
const network = () => new ApiError('sin red', 'network');
const http = (status = 500) => new ApiError('Error interno', 'http', { status, data: null });

const query = (over: Partial<QueryLike> = {}): QueryLike => ({
  queryHash: '["models"]',
  meta: { errorTitle: 'No se pudo cargar la lista de modelos' },
  state: { data: undefined },
  ...over,
});

describe('errorNotifier — consultas REST (T-036)', () => {
  beforeEach(() => useToastStore.getState().clear());
  afterEach(() => useToastStore.getState().clear());

  it('error HTTP sin datos en caché → toast con título de la consulta y Reintentar', () => {
    const retry = vi.fn();
    notifyQueryError(http(), query(), retry);
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]).toMatchObject({
      key: queryToastKey('["models"]'),
      severity: 'error',
      title: 'No se pudo cargar la lista de modelos',
      message: 'Error interno',
      actionLabel: 'Reintentar',
    });
    toasts()[0].onAction?.();
    expect(retry).toHaveBeenCalledOnce();
    expect(toasts()).toHaveLength(0);
  });

  it('con datos en caché no interrumpe al usuario', () => {
    notifyQueryError(http(), query({ state: { data: [] } }), () => {});
    expect(toasts()).toHaveLength(0);
  });

  it('servidor caído → un solo aviso aunque fallen varias consultas', () => {
    notifyQueryError(network(), query(), () => {});
    notifyQueryError(network(), query({ queryHash: '["cameras"]' }), () => {});
    notifyQueryError(network(), query({ queryHash: '["signal"]', meta: { notify: 'network-only' } }), () => {});
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]).toMatchObject({ key: SERVER_TOAST_KEY, title: 'Servidor no disponible' });
  });

  it('el aviso de servidor caído no se recrea en cada fallo del polling', () => {
    const signal = query({ queryHash: '["signal"]', meta: { notify: 'network-only' } });
    notifyQueryError(network(), signal, () => {});
    const id = toasts()[0].id;
    notifyQueryError(network(), signal, () => {});
    expect(toasts()[0].id).toBe(id);
  });

  it("'network-only' ignora errores HTTP", () => {
    notifyQueryError(http(), query({ meta: { notify: 'network-only' } }), () => {});
    expect(toasts()).toHaveLength(0);
  });

  it("'none' nunca avisa", () => {
    notifyQueryError(network(), query({ meta: { notify: 'none' } }), () => {});
    notifyQueryError(http(), query({ meta: { notify: 'none' } }), () => {});
    expect(toasts()).toHaveLength(0);
  });

  it('sin errorTitle usa un título genérico', () => {
    notifyQueryError(http(), query({ meta: undefined }), () => {});
    expect(toasts()[0].title).toBe('No se pudieron cargar los datos');
  });

  it('una respuesta correcta cierra el aviso de servidor y el de esa consulta', () => {
    notifyQueryError(network(), query({ queryHash: '["cameras"]' }), () => {});
    notifyQueryError(http(), query(), () => {});
    useToastStore.getState().show({ key: 'job', severity: 'error', title: 'otro' });
    notifyQuerySuccess({ queryHash: '["models"]' });
    expect(toasts().map((t) => t.key)).toEqual(['job']);
  });
});

describe('errorNotifier — inferencia manual (T-036)', () => {
  beforeEach(() => useToastStore.getState().clear());

  it('muestra el error con Reintentar y lo quita al reintentar', () => {
    const retry = vi.fn();
    notifyManualInferenceError('Modelo no disponible: yolo', retry);
    expect(toasts()[0]).toMatchObject({
      key: MANUAL_INFERENCE_TOAST_KEY,
      title: 'La inferencia falló',
      message: 'Modelo no disponible: yolo',
    });
    toasts()[0].onAction?.();
    expect(retry).toHaveBeenCalledOnce();
    expect(toasts()).toHaveLength(0);
  });

  it('clearManualInferenceError quita solo ese aviso', () => {
    notifyManualInferenceError('x', () => {});
    useToastStore.getState().show({ key: 'job', severity: 'error', title: 'otro' });
    clearManualInferenceError();
    expect(toasts().map((t) => t.key)).toEqual(['job']);
  });
});
