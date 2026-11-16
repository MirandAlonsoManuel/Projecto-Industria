import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReconnectScheduler } from './reconnectScheduler';

describe('ReconnectScheduler', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('ejecuta el reintento tras el retardo inicial', () => {
    const scheduler = new ReconnectScheduler(500);
    const run = vi.fn();
    scheduler.schedule(run);
    expect(scheduler.pending).toBe(true);
    vi.advanceTimersByTime(499);
    expect(run).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(run).toHaveBeenCalledTimes(1);
    expect(scheduler.pending).toBe(false);
  });

  it('duplica el retardo en cada reintento y respeta el máximo', () => {
    const scheduler = new ReconnectScheduler(500, 1500);
    const run = vi.fn();
    scheduler.schedule(run); // 500
    vi.advanceTimersByTime(500);
    scheduler.schedule(run); // 1000
    vi.advanceTimersByTime(999);
    expect(run).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(run).toHaveBeenCalledTimes(2);
    scheduler.schedule(run); // 1500 (tope)
    vi.advanceTimersByTime(1500);
    expect(run).toHaveBeenCalledTimes(3);
    scheduler.schedule(run); // sigue en 1500
    vi.advanceTimersByTime(1500);
    expect(run).toHaveBeenCalledTimes(4);
  });

  it('programar uno nuevo cancela el pendiente: nunca hay dos a la vez', () => {
    const scheduler = new ReconnectScheduler(500);
    const primero = vi.fn();
    const segundo = vi.fn();
    scheduler.schedule(primero);
    scheduler.schedule(segundo);
    vi.advanceTimersByTime(60_000);
    expect(primero).not.toHaveBeenCalled();
    expect(segundo).toHaveBeenCalledTimes(1);
  });

  it('cancel() impide que se ejecute el reintento (cambio de URL / desmontaje)', () => {
    const scheduler = new ReconnectScheduler(500);
    const run = vi.fn();
    scheduler.schedule(run);
    scheduler.cancel();
    expect(scheduler.pending).toBe(false);
    vi.advanceTimersByTime(60_000);
    expect(run).not.toHaveBeenCalled();
  });

  it('cancel() sin nada pendiente no falla', () => {
    expect(() => new ReconnectScheduler().cancel()).not.toThrow();
  });

  it('reset() devuelve el retardo inicial', () => {
    const scheduler = new ReconnectScheduler(500, 30_000);
    const run = vi.fn();
    scheduler.schedule(run);
    vi.advanceTimersByTime(500);
    scheduler.schedule(run);
    vi.advanceTimersByTime(1000);
    scheduler.reset();
    scheduler.schedule(run);
    vi.advanceTimersByTime(500);
    expect(run).toHaveBeenCalledTimes(3);
  });
});