import { useToastStore, type Toast, type ToastSeverity } from '../../../store/toastStore';

/**
 * T-036: muestra los toasts del store en la esquina inferior derecha.
 * Se monta una sola vez (App.tsx). Los errores se anuncian como alerta;
 * el resto, de forma no intrusiva para lectores de pantalla.
 */

const SEVERITY_CLASSES: Record<ToastSeverity, string> = {
  info: 'border-l-[#2f6fe4]',
  success: 'border-l-[#4caf50]',
  warning: 'border-l-[#e0a020]',
  error: 'border-l-[#d64545]',
};

const TITLE_CLASSES: Record<ToastSeverity, string> = {
  info: 'text-[#1f2430] dark:text-white',
  success: 'text-[#2e7d32] dark:text-[#a5d6a7]',
  warning: 'text-[#8a6410] dark:text-[#f3c969]',
  error: 'text-[#d64545] dark:text-[#ff8a8a]',
};

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const isAlert = toast.severity === 'error' || toast.severity === 'warning';
  return (
    <div
      role={isAlert ? 'alert' : 'status'}
      data-severity={toast.severity}
      className={`pointer-events-auto flex w-full gap-3 rounded-xl border-l-4 bg-white px-4 py-3 shadow-lg dark:bg-[#2E2D2D] ${SEVERITY_CLASSES[toast.severity]}`}
    >
      <div className="min-w-0 flex-1">
        <p className={`text-[13px] font-semibold ${TITLE_CLASSES[toast.severity]}`}>{toast.title}</p>
        {toast.message && (
          <p className="mt-0.5 text-[12px] text-[#6b7280] dark:text-[#d1d5db]">{toast.message}</p>
        )}
        {toast.actionLabel && toast.onAction && (
          <button
            type="button"
            onClick={toast.onAction}
            className="mt-2 cursor-pointer rounded-full border border-[#e2e5ea] px-3 py-1 text-[12px] font-semibold text-[#1f2430] hover:bg-[#f1f2f4] dark:border-[#555] dark:text-white dark:hover:bg-[#3a3a3a]"
          >
            {toast.actionLabel}
          </button>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Cerrar notificación"
        className="h-6 w-6 shrink-0 cursor-pointer rounded-md text-[14px] leading-none text-[#9ca3af] hover:bg-[#f1f2f4] hover:text-[#393939] dark:hover:bg-[#3a3a3a] dark:hover:text-white"
      >
        ×
      </button>
    </div>
  );
}

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
      ))}
    </div>
  );
}
