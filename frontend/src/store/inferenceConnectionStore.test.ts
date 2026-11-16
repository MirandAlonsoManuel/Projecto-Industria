import { beforeEach, describe, expect, it } from 'vitest';
import {
  INITIAL_CONNECTION_STATE,
  connectionBadge,
  nextConnectionOwner,
  reduceConnection,
  useInferenceConnectionStore,
  type WsConnectionEvent,
  type WsConnectionState,
} from './inferenceConnectionStore';
import type { StreamSessionStatus } from '../types';

const lost: StreamSessionStatus = {
  state: 'error',
  code: 'CONNECTION_LOST',
  description: 'Se perdió la conexión con el servidor.',
  recoverable: true,
};
const mismatch: StreamSessionStatus = {
  state: 'error',
  code: 'CAMERA_MISMATCH',
  description: 'La sesión activa usa otra cámara.',
  recoverable: false,
};
const stopped: StreamSessionStatus = {
  state: 'stopped',
  code: 'SESSION_STOPPED',
  description: 'Un operador detuvo la sesión.',
  recoverable: false,
};

/** Aplica una secuencia de eventos con tiempos 1, 2, 3… */
function run(events: WsConnectionEvent[], from: WsConnectionState = INITIAL_CONNECTION_STATE) {
  return events.reduce((state, event, i) => reduceConnection(state, event, i + 1), from);
}

describe('reduceConnection (T-035)', () => {
  it('arranca desconectado y sin dueño', () => {
    expect(INITIAL_CONNECTION_STATE).toMatchObject({ status: 'disconnected', owner: null });
  });

  it('primer intento → reconnecting con attempt 0; onopen → connected', () => {
    const conectando = run([{ type: 'connecting', owner: 'a', endpoint: 'stream' }]);
    expect(conectando).toMatchObject({ status: 'reconnecting', attempt: 0, endpoint: 'stream' });

    const abierto = reduceConnection(conectando, { type: 'opened', owner: 'a' }, 9);
    expect(abierto).toMatchObject({ status: 'connected', attempt: 0, lastError: null, changedAt: 9 });
  });

  it('cierre recuperable → reconnecting, y al volver a abrir → connected', () => {
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'inference' },
      { type: 'opened', owner: 'a' },
      { type: 'closed', owner: 'a', session: lost, willReconnect: true },
    ]);
    expect(state).toMatchObject({
      status: 'reconnecting',
      lastError: { code: 'CONNECTION_LOST' },
    });

    const reintento = run(
      [
        { type: 'connecting', owner: 'a', endpoint: 'inference' },
        { type: 'opened', owner: 'a' },
      ],
      state
    );
    expect(reintento).toMatchObject({ status: 'connected', attempt: 0, lastError: null });
  });

  it('cuenta los intentos fallidos seguidos', () => {
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'closed', owner: 'a', session: lost, willReconnect: true },
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'closed', owner: 'a', session: lost, willReconnect: true },
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
    ]);
    expect(state.attempt).toBe(2);
    // El error anterior se conserva mientras se reintenta
    expect(state.lastError?.code).toBe('CONNECTION_LOST');
  });

  it('error no recuperable → error', () => {
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'opened', owner: 'a' },
      { type: 'closed', owner: 'a', session: mismatch, willReconnect: false },
    ]);
    expect(state).toMatchObject({ status: 'error', lastError: { code: 'CAMERA_MISMATCH' } });
  });

  it('error recuperable que agotó el tope de reintentos → error', () => {
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'closed', owner: 'a', session: lost, willReconnect: false },
    ]);
    expect(state.status).toBe('error');
  });

  it('fin intencional de la sesión → disconnected', () => {
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'opened', owner: 'a' },
      { type: 'closed', owner: 'a', session: stopped, willReconnect: false },
    ]);
    expect(state).toMatchObject({ status: 'disconnected', lastError: { code: 'SESSION_STOPPED' } });
  });

  it('onerror solo guarda el mensaje, no cambia el estado', () => {
    const abierto = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'opened', owner: 'a' },
    ]);
    const state = reduceConnection(abierto, { type: 'errored', owner: 'a', message: 'falló' }, 5);
    expect(state.status).toBe('connected');
    expect(state.lastError).toEqual({ code: null, description: 'falló' });
    expect(state.changedAt).toBe(abierto.changedAt);
  });

  it('al desmontar (released) queda disconnected y sin dueño', () => {
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'opened', owner: 'a' },
      { type: 'released', owner: 'a' },
    ]);
    expect(state).toMatchObject({ status: 'disconnected', owner: null, endpoint: null });
  });

  it('los eventos de un socket viejo no afectan al nuevo', () => {
    // Cambio de modo: el socket "b" toma el control antes de que "a" termine de cerrar
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'opened', owner: 'a' },
      { type: 'connecting', owner: 'b', endpoint: 'inference' },
      { type: 'opened', owner: 'b' },
      { type: 'closed', owner: 'a', session: lost, willReconnect: true },
      { type: 'errored', owner: 'a', message: 'viejo' },
      { type: 'released', owner: 'a' },
    ]);
    expect(state).toMatchObject({
      status: 'connected',
      owner: 'b',
      endpoint: 'inference',
      lastError: null,
    });
  });

  it('un dueño nuevo empieza sin error previo y en attempt 0', () => {
    const state = run([
      { type: 'connecting', owner: 'a', endpoint: 'stream' },
      { type: 'closed', owner: 'a', session: mismatch, willReconnect: false },
      { type: 'connecting', owner: 'b', endpoint: 'stream' },
    ]);
    expect(state).toMatchObject({ status: 'reconnecting', attempt: 0, lastError: null });
  });
});

describe('useInferenceConnectionStore (T-035)', () => {
  beforeEach(() => {
    useInferenceConnectionStore.setState(INITIAL_CONNECTION_STATE);
  });

  it('las acciones aplican las transiciones', () => {
    const store = useInferenceConnectionStore.getState();
    store.socketConnecting('x', 'inference');
    expect(useInferenceConnectionStore.getState().status).toBe('reconnecting');
    store.socketOpened('x');
    expect(useInferenceConnectionStore.getState().status).toBe('connected');
    store.socketErrored('x', 'algo');
    store.socketClosed('x', lost, true);
    expect(useInferenceConnectionStore.getState().status).toBe('reconnecting');
    store.socketReleased('x');
    expect(useInferenceConnectionStore.getState()).toMatchObject({
      status: 'disconnected',
      owner: null,
    });
  });

  it('nextConnectionOwner nunca repite', () => {
    expect(nextConnectionOwner('stream')).not.toBe(nextConnectionOwner('stream'));
  });
});

describe('connectionBadge (T-035)', () => {
  it.each([
    [{ status: 'connected', attempt: 0, lastError: null }, 'connected', 'Conectado'],
    [{ status: 'reconnecting', attempt: 0, lastError: null }, 'connecting', 'Conectando...'],
    [{ status: 'reconnecting', attempt: 3, lastError: null }, 'connecting', 'Reconectando...'],
    [{ status: 'disconnected', attempt: 0, lastError: null }, 'disconnected', 'Sin conexión'],
    [{ status: 'error', attempt: 0, lastError: null }, 'error', 'Error de conexión'],
  ] as const)('%o → %s / %s', (state, status, label) => {
    expect(connectionBadge(state)).toMatchObject({ status, label });
  });

  it('muestra la descripción del último error', () => {
    expect(
      connectionBadge({
        status: 'error',
        attempt: 0,
        lastError: { code: 'CAMERA_MISMATCH', description: 'Otra cámara' },
      }).detail
    ).toBe('Otra cámara');
  });
});
