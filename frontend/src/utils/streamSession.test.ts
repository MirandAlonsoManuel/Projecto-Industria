import { describe, expect, it } from 'vitest';
import {
  CONNECTING_STATUS,
  ERROR_RECOVERABILITY,
  STREAM_FROZEN_CLOSE_CODE,
  parseControlMessage,
  shouldReconnect,
  statusFromClose,
} from './streamSession';

/** Mensajes tal como los manda hoy backend/app/services/stream_runner.py */
const bienvenidaActual = JSON.stringify({
  connected: true,
  camera_id: '0',
  client_id: 'abc',
  state: 'streaming', // estado del gestor de cámara, no de la sesión
  started_by: 'client',
  error: null,
  description: 'Cámara detectada. Iniciando inferencia.',
});

const finActual = (error: string, description = 'detalle') =>
  JSON.stringify({ connected: false, camera_id: '0', error, description });

describe('parseControlMessage — backend actual', () => {
  it('la bienvenida pasa a active aunque traiga el state del gestor', () => {
    expect(parseControlMessage(bienvenidaActual)).toEqual({
      state: 'active',
      code: null,
      description: 'Cámara detectada. Iniciando inferencia.',
      recoverable: true,
    });
  });

  it.each([
    ['SESSION_STOPPED', 'stopped'],
    ['SERVICE_SHUTDOWN', 'stopped'],
    ['SERVICE_SHUTTING_DOWN', 'stopped'],
    ['CLIENT_DISCONNECTED', 'disconnected'],
  ])('%s es un fin intencional (%s) y no se reintenta', (code, state) => {
    const status = parseControlMessage(finActual(code));
    expect(status).toMatchObject({ state, code, recoverable: false });
    expect(shouldReconnect(status!)).toBe(false);
  });

  it.each(['CAMERA_BUSY', 'CAMERA_UNAVAILABLE', 'CAMERA_STALLED', 'CAMERA_READ_ERROR', 'STREAM_ERROR'])(
    '%s es un error recuperable',
    (code) => {
      const status = parseControlMessage(finActual(code, 'falló'));
      expect(status).toEqual({ state: 'error', code, description: 'falló', recoverable: true });
      expect(shouldReconnect(status!)).toBe(true);
    }
  );

  it('CAMERA_MISMATCH es un error no recuperable', () => {
    const status = parseControlMessage(finActual('CAMERA_MISMATCH'));
    expect(status).toMatchObject({ state: 'error', recoverable: false });
    expect(shouldReconnect(status!)).toBe(false);
  });

  it('un código desconocido no se reintenta', () => {
    expect(parseControlMessage(finActual('ALGO_NUEVO'))).toMatchObject({
      state: 'error',
      code: 'ALGO_NUEVO',
      recoverable: false,
    });
  });

  it.each(['{no-json', '[]', '"texto"', '{}', 'null'])('ignora %s', (data) => {
    expect(parseControlMessage(data)).toBeNull();
  });
});

describe('parseControlMessage — contrato HU-12', () => {
  it('respeta el state declarado', () => {
    expect(parseControlMessage(JSON.stringify({ type: 'state', state: 'connecting' }))).toEqual(
      CONNECTING_STATUS
    );
    expect(parseControlMessage(JSON.stringify({ type: 'state', state: 'active' }))).toMatchObject({
      state: 'active',
    });
  });

  it('el recoverable del backend gana sobre la tabla local', () => {
    const status = parseControlMessage(
      JSON.stringify({
        type: 'error',
        state: 'error',
        code: 'CAMERA_BUSY',
        description: 'ocupada',
        recoverable: false,
      })
    );
    expect(status).toEqual({
      state: 'error',
      code: 'CAMERA_BUSY',
      description: 'ocupada',
      recoverable: false,
    });
  });

  it('sin recoverable usa la tabla local', () => {
    const status = parseControlMessage(
      JSON.stringify({ type: 'error', state: 'error', code: 'CAMERA_STALLED' })
    );
    expect(status?.recoverable).toBe(true);
  });

  it('acepta stopped y disconnected como estados finales', () => {
    expect(
      parseControlMessage(JSON.stringify({ type: 'state', state: 'stopped', code: 'SESSION_STOPPED' }))
    ).toMatchObject({ state: 'stopped', recoverable: false });
    expect(
      parseControlMessage(JSON.stringify({ type: 'state', state: 'disconnected' }))
    ).toMatchObject({ state: 'disconnected', recoverable: false });
  });
});

describe('statusFromClose', () => {
  it('conserva el aviso del servidor recibido antes del cierre', () => {
    const aviso = parseControlMessage(finActual('SESSION_STOPPED'))!;
    expect(statusFromClose(1000, aviso)).toBe(aviso);
  });

  it('un cierre sin aviso estando activo es pérdida de conexión recuperable', () => {
    const activo = parseControlMessage(bienvenidaActual);
    const status = statusFromClose(1006, activo);
    expect(status).toMatchObject({ state: 'error', code: 'CONNECTION_LOST', recoverable: true });
    expect(status.description).toBeTruthy();
    expect(shouldReconnect(status)).toBe(true);
  });

  it('un cierre antes de cualquier mensaje también se reintenta', () => {
    expect(shouldReconnect(statusFromClose(1006, null))).toBe(true);
  });

  it('el cierre del watchdog se reporta como stream congelado', () => {
    expect(statusFromClose(STREAM_FROZEN_CLOSE_CODE, CONNECTING_STATUS)).toMatchObject({
      state: 'error',
      code: 'STREAM_FROZEN',
      recoverable: true,
    });
  });
});

describe('ERROR_RECOVERABILITY', () => {
  it('cubre todos los códigos de cierre del backend (CLOSE_CODES)', () => {
    const codigosBackend = [
      'CAMERA_BUSY',
      'CAMERA_MISMATCH',
      'CAMERA_UNAVAILABLE',
      'CAMERA_NO_FRAMES',
      'STREAM_CLOSED',
      'SERVICE_SHUTTING_DOWN',
      'SERVICE_SHUTDOWN',
      'CAMERA_READ_ERROR',
      'CAMERA_STALLED',
      'STREAM_ERROR',
    ];
    // SESSION_STOPPED y CLIENT_DISCONNECTED no son errores: son fines de sesión
    for (const code of codigosBackend) {
      expect(ERROR_RECOVERABILITY, code).toHaveProperty(code);
    }
  });
});
