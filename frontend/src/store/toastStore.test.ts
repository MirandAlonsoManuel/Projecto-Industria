import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_TOASTS, useToastStore } from './toastStore';

const toasts = () => useToastStore.getState().toasts;
const show = useToastStore.getState().show;

describe('toastStore (T-036)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useToastStore.getState().clear();
  });
  afterEach(() => {
    useToastStore.getState().clear();
    vi.useRealTimers();
  });

  it('agrega un toast con sus datos', () => {
    show({ severity: 'error', title: 'Falló', message: 'detalle', actionLabel: 'Reintentar', onAction: () => {} });
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]).toMatchObject({ severity: 'error', title: 'Falló', actionLabel: 'Reintentar' });
  });

  it('info y success se cierran solos', () => {
    show({ severity: 'success', title: 'Listo' });
    vi.advanceTimersByTime(3_999);
    expect(toasts()).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(toasts()).toHaveLength(0);
  });

  it('warning y error se quedan hasta cerrarlos', () => {
    const id = show({ severity: 'error', title: 'Falló' });
    vi.advanceTimersByTime(60_000);
    expect(toasts()).toHaveLength(1);
    useToastStore.getState().dismiss(id);
    expect(toasts()).toHaveLength(0);
  });

  it('respeta una duración explícita', () => {
    show({ severity: 'warning', title: 'Aviso', durationMs: 1_000 });
    vi.advanceTimersByTime(1_000);
    expect(toasts()).toHaveLength(0);
  });

  it('la misma key reemplaza al anterior en lugar de apilarse', () => {
    show({ key: 'job', severity: 'warning', title: 'En pausa' });
    show({ key: 'job', severity: 'warning', title: 'En pausa' });
    show({ key: 'job', severity: 'success', title: 'Reanudada' });
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0].title).toBe('Reanudada');
  });

  it('un aviso idéntico con la misma key conserva el existente', () => {
    const id = show({ key: 'server', severity: 'warning', title: 'Caído', message: 'x' });
    expect(show({ key: 'server', severity: 'warning', title: 'Caído', message: 'x' })).toBe(id);
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0].id).toBe(id);
  });

  it('el reemplazo cancela el temporizador del anterior', () => {
    show({ key: 'job', severity: 'success', title: 'Reanudada' }); // se cerraría a los 4 s
    vi.advanceTimersByTime(3_000);
    show({ key: 'job', severity: 'error', title: 'Detenida' }); // fijo
    vi.advanceTimersByTime(5_000);
    expect(toasts().map((t) => t.title)).toEqual(['Detenida']);
  });

  it('dismissByKey cierra solo los de esa key', () => {
    show({ key: 'job', severity: 'error', title: 'A' });
    show({ severity: 'error', title: 'B' });
    useToastStore.getState().dismissByKey('job');
    expect(toasts().map((t) => t.title)).toEqual(['B']);
  });

  it(`muestra como máximo ${MAX_TOASTS} y descarta los más viejos`, () => {
    for (let i = 1; i <= MAX_TOASTS + 2; i += 1) show({ severity: 'error', title: `T${i}` });
    expect(toasts()).toHaveLength(MAX_TOASTS);
    expect(toasts()[0].title).toBe('T3');
  });
});
