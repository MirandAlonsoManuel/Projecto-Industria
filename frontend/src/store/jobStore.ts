/**
 * T-036: estado global del job de inspección (antes era estado local de MainPanel).
 *
 * Estados (JobStatus): idle → running → stopped | error.
 * Mientras corre, un error recuperable no lo detiene: lo marca `paused` hasta que
 * la conexión se recupera. Un error no recuperable lo pasa a `error`.
 */
import { create } from 'zustand';
import type { Job } from '../types';
import type { JobErrorInfo } from '../utils/jobErrors';

export interface JobState {
  job: Job;
  /** Último error del job (también se refleja en job.errorMessage) */
  error: JobErrorInfo | null;
  /** true = corriendo, pero en pausa por un error recuperable (reconectando) */
  paused: boolean;
}

export type JobEvent =
  | { type: 'start'; cameraId: string; modelId: string }
  | { type: 'stop' }
  | { type: 'pause'; error: JobErrorInfo }
  | { type: 'resume' }
  | { type: 'fail'; error: JobErrorInfo }
  | { type: 'configure'; cameraId?: string; modelId?: string };

export const INITIAL_JOB_STATE: JobState = {
  job: { id: 'job-01', cameraId: '0', modelId: '', status: 'idle' },
  error: null,
  paused: false,
};

/** Transición pura: estado actual + evento → estado nuevo. */
export function reduceJob(state: JobState, event: JobEvent, now: number): JobState {
  const { job } = state;
  const running = job.status === 'running';

  switch (event.type) {
    case 'start':
      if (running) return state;
      return {
        job: {
          ...job,
          cameraId: event.cameraId,
          modelId: event.modelId,
          status: 'running',
          startedAt: now,
          stoppedAt: undefined,
          errorMessage: undefined,
        },
        error: null,
        paused: false,
      };

    case 'stop':
      if (!running) return state;
      return {
        job: { ...job, status: 'stopped', stoppedAt: now },
        error: null,
        paused: false,
      };

    case 'pause':
      if (!running) return state;
      return { ...state, error: event.error, paused: true };

    case 'resume':
      if (!running || !state.paused) return state;
      return { ...state, error: null, paused: false };

    case 'fail':
      // Solo un job en curso puede fallar; un error tardío no reabre uno detenido
      if (!running) return state;
      return {
        job: {
          ...job,
          status: 'error',
          stoppedAt: now,
          errorMessage: event.error.message,
        },
        error: event.error,
        paused: false,
      };

    case 'configure':
      // Cambiar cámara o modelo deja el job listo para un inicio limpio
      return {
        job: {
          ...job,
          cameraId: event.cameraId ?? job.cameraId,
          modelId: event.modelId ?? job.modelId,
          status: 'idle',
          startedAt: undefined,
          stoppedAt: undefined,
          errorMessage: undefined,
        },
        error: null,
        paused: false,
      };
  }
}

interface JobActions {
  start: (cameraId: string, modelId: string) => void;
  stop: () => void;
  pause: (error: JobErrorInfo) => void;
  resume: () => void;
  fail: (error: JobErrorInfo) => void;
  configure: (changes: { cameraId?: string; modelId?: string }) => void;
}

export const useJobStore = create<JobState & JobActions>((set) => {
  const dispatch = (event: JobEvent) => set((state) => reduceJob(state, event, Date.now()));
  return {
    ...INITIAL_JOB_STATE,
    start: (cameraId, modelId) => dispatch({ type: 'start', cameraId, modelId }),
    stop: () => dispatch({ type: 'stop' }),
    pause: (error) => dispatch({ type: 'pause', error }),
    resume: () => dispatch({ type: 'resume' }),
    fail: (error) => dispatch({ type: 'fail', error }),
    configure: (changes) => dispatch({ type: 'configure', ...changes }),
  };
});
