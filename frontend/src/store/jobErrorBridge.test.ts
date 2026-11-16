import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  INITIAL_CONNECTION_STATE,
  useInferenceConnectionStore,
} from './inferenceConnectionStore';
import { INITIAL_JOB_STATE, useJobStore } from './jobStore';
import { useToastStore } from './toastStore';
import { JOB_TOAST_KEY, RESUME_STABLE_MS, retryJob, startJobErrorBridge } from './jobErrorBridge';
import type { StreamSessionStatus } from '../types';

const conn = () => useInferenceConnectionStore.getState();
const job = () => useJobStore.getState();
const toasts = () => useToastStore.getState().toasts;

const session = (code: string, description: string, state: StreamSessionStatus['state'] = 'error'): StreamSessionStatus => ({
  state,
  code,
  description,
  recoverable: true,
});

/** Socket de inferencia que abre bien */
function openInference(owner = 'inference-1') {
  conn().socketConnecting(owner, 'inference');
  conn().socketOpened(owner);
}

describe('jobErrorBridge (T-036)', () => {
  let stopBridge: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    useInferenceConnectionStore.setState(INITIAL_CONNECTION_STATE);
    useJobStore.setState(INITIAL_JOB_STATE);
    useToastStore.getState().clear();
    stopBridge = startJobErrorBridge();
    job().start('0', 'yolo');
  });

  afterEach(() => {
    stopBridge();
    useToastStore.getState().clear();
    vi.useRealTimers();
  });

  it('un inicio normal no genera avisos', () => {
    openInference();
    expect(job()).toMatchObject({ job: { status: 'running' }, paused: false });
    expect(toasts()).toHaveLength(0);
  });

  it('pérdida de conexión → job en pausa con un solo aviso aunque reintente varias veces', () => {
    openInference();
    for (let i = 0; i < 3; i += 1) {
      conn().socketClosed('inference-1', session('CONNECTION_LOST', 'caída'), true);
      conn().socketConnecting('inference-1', 'inference');
    }
    expect(job()).toMatchObject({ job: { status: 'running' }, paused: true });
    expect(job().error?.code).toBe('CONNECTION_LOST');
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]).toMatchObject({ key: JOB_TOAST_KEY, severity: 'warning', title: 'Inspección en pausa' });
  });

  it('si la conexión vuelve y se sostiene, el job se reanuda', () => {
    openInference();
    conn().socketClosed('inference-1', session('CONNECTION_LOST', 'caída'), true);
    conn().socketConnecting('inference-1', 'inference');
    conn().socketOpened('inference-1');

    // Aún no: la conexión debe sostenerse
    vi.advanceTimersByTime(RESUME_STABLE_MS - 1);
    expect(job().paused).toBe(true);

    vi.advanceTimersByTime(1);
    expect(job()).toMatchObject({ paused: false, error: null });
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]).toMatchObject({ severity: 'success', title: 'Inspección reanudada' });
  });

  it('si abre y vuelve a caer enseguida, no se anuncia "reanudada"', () => {
    openInference();
    conn().socketClosed('inference-1', session('STREAM_ERROR', 'falló'), true);
    conn().socketConnecting('inference-1', 'inference');
    conn().socketOpened('inference-1');
    vi.advanceTimersByTime(1_000);
    conn().socketClosed('inference-1', session('STREAM_ERROR', 'falló'), true);
    vi.advanceTimersByTime(RESUME_STABLE_MS * 2);

    expect(job().paused).toBe(true);
    expect(toasts().map((t) => t.title)).toEqual(['Inspección en pausa']);
  });

  it('un ROI inválido detiene el job en vez de reintentar', () => {
    openInference();
    conn().socketClosed(
      'inference-1',
      session('STREAM_ERROR', 'ROI está fuera de los límites de la imagen.'),
      true
    );
    expect(job()).toMatchObject({ job: { status: 'error' }, error: { code: 'INVALID_ROI' } });
    expect(toasts()[0]).toMatchObject({ severity: 'error', actionLabel: 'Reintentar' });
  });

  it('error no recuperable → job en error con toast y acción Reintentar', () => {
    openInference();
    conn().socketClosed('inference-1', session('CAMERA_MISMATCH', 'otra cámara'), false);
    expect(job()).toMatchObject({ job: { status: 'error' }, error: { code: 'CAMERA_MISMATCH' } });
    expect(toasts()[0].title).toBe('Inspección detenida: Cámara distinta');
  });

  it('sesión detenida por un operador → job en error', () => {
    openInference();
    conn().socketClosed('inference-1', session('SESSION_STOPPED', 'detenida', 'stopped'), false);
    expect(job()).toMatchObject({ job: { status: 'error' }, error: { code: 'SESSION_STOPPED' } });
  });

  it('la acción Reintentar del toast vuelve a iniciar el job', () => {
    openInference();
    conn().socketClosed('inference-1', session('CAMERA_MISMATCH', 'otra cámara'), false);
    toasts()[0].onAction?.();
    expect(job()).toMatchObject({ job: { status: 'running', cameraId: '0', modelId: 'yolo' } });
    expect(toasts()).toHaveLength(0);
  });

  it('retryJob funciona igual desde la UI', () => {
    openInference();
    conn().socketClosed('inference-1', session('CAMERA_MISMATCH', 'x'), false);
    retryJob();
    expect(job().job.status).toBe('running');
  });

  it('ignora el socket de video normal y los sockets liberados', () => {
    conn().socketConnecting('stream-1', 'stream');
    conn().socketClosed('stream-1', session('CAMERA_MISMATCH', 'x'), false);
    conn().socketReleased('stream-1');
    expect(job()).toMatchObject({ job: { status: 'running' }, paused: false });
    expect(toasts()).toHaveLength(0);
  });

  it('con el job detenido no reacciona a errores', () => {
    job().stop();
    openInference();
    conn().socketClosed('inference-1', session('CAMERA_MISMATCH', 'x'), false);
    expect(job().job.status).toBe('stopped');
    expect(toasts()).toHaveLength(0);
  });

  it('al dejar de escuchar ya no reacciona', () => {
    stopBridge();
    openInference();
    conn().socketClosed('inference-1', session('CAMERA_MISMATCH', 'x'), false);
    expect(job().job.status).toBe('running');
    stopBridge = () => {};
  });
});
