/**
 * T-036: notificaciones tipo toast, globales para toda la app.
 *
 * Reglas:
 *  - Un toast con `key` reemplaza al que ya tenga esa key (no se apilan avisos
 *    repetidos, p. ej. durante los reintentos de conexión). Si el contenido es
 *    idéntico, se conserva el existente.
 *  - info / success se cierran solos; warning y error se quedan hasta que el
 *    usuario los cierre (salvo que se pase `durationMs`).
 */
import { create } from 'zustand';

export type ToastSeverity = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  key: string | null;
  severity: ToastSeverity;
  title: string;
  message: string | null;
  actionLabel: string | null;
  onAction: (() => void) | null;
  /** null = no se cierra solo */
  durationMs: number | null;
}

export interface ToastInput {
  key?: string;
  severity: ToastSeverity;
  title: string;
  message?: string | null;
  actionLabel?: string;
  onAction?: () => void;
  durationMs?: number | null;
}

/** Duración por defecto: los avisos informativos se cierran solos */
export const DEFAULT_DURATION_MS: Record<ToastSeverity, number | null> = {
  info: 4_000,
  success: 4_000,
  warning: null,
  error: null,
};

/** Máximo de toasts visibles; los más viejos se descartan */
export const MAX_TOASTS = 4;

interface ToastState {
  toasts: Toast[];
  show: (input: ToastInput) => string;
  dismiss: (id: string) => void;
  dismissByKey: (key: string) => void;
  clear: () => void;
}

let toastSeq = 0;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

function clearTimer(id: string) {
  const timer = timers.get(id);
  if (timer !== undefined) {
    clearTimeout(timer);
    timers.delete(id);
  }
}

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],

  show: (input) => {
    // Aviso idéntico ya visible: se conserva (no parpadea ni se vuelve a anunciar)
    if (input.key) {
      const same = get().toasts.find(
        (t) =>
          t.key === input.key &&
          t.severity === input.severity &&
          t.title === input.title &&
          t.message === (input.message ?? null)
      );
      if (same) return same.id;
    }

    toastSeq += 1;
    const id = `toast-${toastSeq}`;
    const toast: Toast = {
      id,
      key: input.key ?? null,
      severity: input.severity,
      title: input.title,
      message: input.message ?? null,
      actionLabel: input.actionLabel ?? null,
      onAction: input.onAction ?? null,
      durationMs:
        input.durationMs !== undefined ? input.durationMs : DEFAULT_DURATION_MS[input.severity],
    };

    set((state) => {
      // Mismo key: se reemplaza el anterior (y su temporizador)
      const replaced = toast.key ? state.toasts.filter((t) => t.key === toast.key) : [];
      replaced.forEach((t) => clearTimer(t.id));
      const rest = state.toasts.filter((t) => !replaced.includes(t));
      const next = [...rest, toast];
      const dropped = next.slice(0, Math.max(0, next.length - MAX_TOASTS));
      dropped.forEach((t) => clearTimer(t.id));
      return { toasts: next.slice(-MAX_TOASTS) };
    });

    if (toast.durationMs !== null) {
      timers.set(
        id,
        setTimeout(() => get().dismiss(id), toast.durationMs)
      );
    }
    return id;
  },

  dismiss: (id) => {
    clearTimer(id);
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },

  dismissByKey: (key) => {
    const ids = get()
      .toasts.filter((t) => t.key === key)
      .map((t) => t.id);
    ids.forEach(clearTimer);
    set((state) => ({ toasts: state.toasts.filter((t) => t.key !== key) }));
  },

  clear: () => {
    get().toasts.forEach((t) => clearTimer(t.id));
    set({ toasts: [] });
  },
}));
