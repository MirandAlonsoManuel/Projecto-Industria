import { describe, expect, it } from 'vitest';
import { INITIAL_JOB_STATE, reduceJob, type JobEvent, type JobState } from './jobStore';
import { describeJobError } from '../utils/jobErrors';

const lost = describeJobError('CONNECTION_LOST');
const mismatch = describeJobError('CAMERA_MISMATCH');

function run(events: JobEvent[], from: JobState = INITIAL_JOB_STATE): JobState {
  return events.reduce((state, event, i) => reduceJob(state, event, (i + 1) * 100), from);
}

const start: JobEvent = { type: 'start', cameraId: '0', modelId: 'yolo' };

describe('reduceJob (T-036)', () => {
  it('arranca en idle sin error', () => {
    expect(INITIAL_JOB_STATE).toMatchObject({ job: { status: 'idle' }, error: null, paused: false });
  });

  it('start → running con cámara, modelo y hora de inicio', () => {
    expect(run([start]).job).toMatchObject({
      status: 'running',
      cameraId: '0',
      modelId: 'yolo',
      startedAt: 100,
    });
  });

  it('stop → stopped', () => {
    expect(run([start, { type: 'stop' }]).job).toMatchObject({ status: 'stopped', stoppedAt: 200 });
  });

  it('pause mantiene el job corriendo y guarda el error; resume lo limpia', () => {
    const pausado = run([start, { type: 'pause', error: lost }]);
    expect(pausado).toMatchObject({ job: { status: 'running' }, paused: true, error: lost });

    const reanudado = reduceJob(pausado, { type: 'resume' }, 999);
    expect(reanudado).toMatchObject({ job: { status: 'running' }, paused: false, error: null });
  });

  it('fail → error con mensaje, y sale de la pausa', () => {
    const state = run([start, { type: 'pause', error: lost }, { type: 'fail', error: mismatch }]);
    expect(state).toMatchObject({
      job: { status: 'error', errorMessage: mismatch.message, stoppedAt: 300 },
      error: mismatch,
      paused: false,
    });
  });

  it('un error tardío no afecta a un job ya detenido', () => {
    const detenido = run([start, { type: 'stop' }]);
    expect(reduceJob(detenido, { type: 'fail', error: mismatch }, 5)).toBe(detenido);
    expect(reduceJob(detenido, { type: 'pause', error: lost }, 5)).toBe(detenido);
  });

  it('se puede reintentar después de un error', () => {
    const state = run([start, { type: 'fail', error: mismatch }, start]);
    expect(state).toMatchObject({
      job: { status: 'running', errorMessage: undefined, startedAt: 300 },
      error: null,
    });
  });

  it('start sobre un job corriendo no lo reinicia', () => {
    const corriendo = run([start]);
    expect(reduceJob(corriendo, start, 5)).toBe(corriendo);
  });

  it('configure deja el job en idle con la nueva cámara o modelo', () => {
    const state = run([
      start,
      { type: 'fail', error: mismatch },
      { type: 'configure', modelId: 'otro' },
    ]);
    expect(state).toMatchObject({
      job: { status: 'idle', cameraId: '0', modelId: 'otro', startedAt: undefined },
      error: null,
    });
  });
});
