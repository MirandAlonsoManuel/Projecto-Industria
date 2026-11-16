/**
 * T-036: conecta el estado del WebSocket de inferencia (store de T-035) con el job
 * y con los toasts. No usa efectos de React: se suscribe a los stores y se puede
 * probar sin montar componentes.
 *
 * Mientras el job corre y el socket activo es /ws/inference-stream:
 *  - error recuperable (reconectando)  → job en pausa + toast de aviso
 *  - vuelve la conexión y se sostiene  → job reanudado + toast de éxito
 *  - error no recuperable o tope       → job en error + toast con "Reintentar"
 *  - fin de sesión (stop / expulsión)  → job en error + toast con "Reintentar"
 */
import { useInferenceConnectionStore, type WsConnectionState } from './inferenceConnectionStore';
import { useJobStore } from './jobStore';
import { useToastStore } from './toastStore';
import { describeJobError, type JobErrorInfo } from '../utils/jobErrors';

/** Todos los toasts del job comparten esta key: nunca se apilan */
export const JOB_TOAST_KEY = 'job';

/**
 * La conexión debe sostenerse este tiempo para dar el job por reanudado. Evita
 * avisos "reanudada / en pausa" en bucle cuando el socket abre y falla enseguida.
 */
export const RESUME_STABLE_MS = 5_000;

/** Toast de un job que se detuvo por error, con acción para reintentarlo */
export function notifyJobFailed(error: JobErrorInfo): void {
  useToastStore.getState().show({
    key: JOB_TOAST_KEY,
    severity: 'error',
    title: `Inspección detenida: ${error.title}`,
    message: error.message,
    actionLabel: 'Reintentar',
    onAction: retryJob,
  });
}

/** Vuelve a iniciar el job con la misma cámara y modelo */
export function retryJob(): void {
  const { job, start } = useJobStore.getState();
  useToastStore.getState().dismissByKey(JOB_TOAST_KEY);
  start(job.cameraId, job.modelId);
}

function failJob(error: JobErrorInfo): void {
  useJobStore.getState().fail(error);
  notifyJobFailed(error);
}

/**
 * Empieza a escuchar. Devuelve la función para dejar de hacerlo
 * (pensada para el `return` de un useEffect).
 */
export function startJobErrorBridge(): () => void {
  let resumeTimer: ReturnType<typeof setTimeout> | null = null;

  const cancelResume = () => {
    if (resumeTimer !== null) {
      clearTimeout(resumeTimer);
      resumeTimer = null;
    }
  };

  const scheduleResume = (owner: string | null) => {
    if (resumeTimer !== null) return;
    resumeTimer = setTimeout(() => {
      resumeTimer = null;
      const conn = useInferenceConnectionStore.getState();
      const { job, paused, resume } = useJobStore.getState();
      // Solo si nada cambió mientras se esperaba
      if (job.status !== 'running' || !paused) return;
      if (conn.status !== 'connected' || conn.owner !== owner) return;
      resume();
      useToastStore.getState().show({
        key: JOB_TOAST_KEY,
        severity: 'success',
        title: 'Inspección reanudada',
        message: 'La conexión con la cámara se recuperó.',
      });
    }, RESUME_STABLE_MS);
  };

  const handle = (conn: WsConnectionState) => {
    const { job, paused, error, pause } = useJobStore.getState();
    if (job.status !== 'running') {
      cancelResume();
      return;
    }
    // Solo cuenta el socket de inferencia; el de video normal o uno liberado se ignoran
    if (conn.endpoint !== 'inference') return;

    switch (conn.status) {
      case 'connected':
        if (paused) scheduleResume(conn.owner);
        return;

      case 'reconnecting': {
        cancelResume();
        // Primer intento al iniciar: aún no hay error que reportar
        if (conn.lastError === null) return;
        const info = describeJobError(conn.lastError.code, conn.lastError.description);
        if (!info.recoverable) {
          failJob(info);
          return;
        }
        // Mismo error ya reportado: no se repite el aviso en cada reintento
        if (paused && error?.code === info.code) return;
        pause(info);
        useToastStore.getState().show({
          key: JOB_TOAST_KEY,
          severity: 'warning',
          title: 'Inspección en pausa',
          message: `${info.title}. ${info.message}`,
        });
        return;
      }

      case 'error':
      case 'disconnected':
        cancelResume();
        failJob(
          describeJobError(conn.lastError?.code ?? 'CONNECTION_LOST', conn.lastError?.description)
        );
        return;
    }
  };

  const unsubscribe = useInferenceConnectionStore.subscribe(handle);
  return () => {
    unsubscribe();
    cancelResume();
  };
}
