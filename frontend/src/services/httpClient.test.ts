import { describe, expect, it } from 'vitest';
import { ApiError, NETWORK_ERROR_MESSAGE, isApiError, normalizeApiError } from './httpClient';
import { parseInferenceError } from './inferenceApi';

/** Error con la forma que produce axios */
function axiosError(response?: { status: number; data?: unknown }) {
  return { isAxiosError: true, message: 'axios', response, config: {}, toJSON: () => ({}) };
}

describe('normalizeApiError (T-036)', () => {
  it('sin respuesta → error de red', () => {
    const err = normalizeApiError(axiosError());
    expect(isApiError(err)).toBe(true);
    expect(err).toMatchObject({ kind: 'network', status: null, message: NETWORK_ERROR_MESSAGE });
  });

  it.each([
    [401, 'No autorizado. Por favor inicia sesión de nuevo.'],
    [403, 'Acceso denegado.'],
    [404, 'El recurso solicitado no existe.'],
    [500, 'Error interno del servidor. Inténtalo más tarde.'],
    [503, 'Error interno del servidor. Inténtalo más tarde.'],
  ])('HTTP %i conserva el mensaje de siempre', (status, message) => {
    expect(normalizeApiError(axiosError({ status }))).toMatchObject({ kind: 'http', status, message });
  });

  it('400 usa el detail del backend', () => {
    expect(normalizeApiError(axiosError({ status: 400, data: { detail: 'Imagen inválida' } }))).toMatchObject({
      message: 'Imagen inválida',
    });
  });

  it('conserva la respuesta original (status y body)', () => {
    const err = normalizeApiError(axiosError({ status: 503, data: { detail: 'yolo sin cargar' } })) as ApiError;
    expect(err.response).toEqual({ status: 503, data: { detail: 'yolo sin cargar' } });
  });

  it('lo que no es de axios pasa igual', () => {
    const original = new Error('otro');
    expect(normalizeApiError(original)).toBe(original);
  });
});

describe('parseInferenceError con ApiError (T-036)', () => {
  it('un 503 vuelve a mostrar el detalle del modelo', () => {
    const err = normalizeApiError(axiosError({ status: 503, data: { detail: 'yolo sin cargar' } }));
    expect(parseInferenceError(err)).toBe('Modelo no disponible: yolo sin cargar');
  });

  it('un error de red sigue diciendo que no se pudo contactar', () => {
    expect(parseInferenceError(normalizeApiError(axiosError()))).toBe(
      'No se pudo contactar al servidor de inferencia.'
    );
  });
});
