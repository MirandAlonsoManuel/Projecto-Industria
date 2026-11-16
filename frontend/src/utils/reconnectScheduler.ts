/**
 * HU-11: programador de reintentos de conexión con backoff exponencial.
 *
 * Garantiza UN solo reintento pendiente a la vez: programar uno nuevo cancela el
 * anterior, y `cancel()` lo anula del todo. Así, cuando el hook cambia de URL
 * (Iniciar / Detener inspección) no queda ningún temporizador de la conexión
 * anterior que abra un socket de más y compita por la cámara (CAMERA_BUSY).
 */
export class ReconnectScheduler {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private nextDelay: number;
  private readonly initialDelayMs: number;
  private readonly maxDelayMs: number;

  constructor(initialDelayMs = 500, maxDelayMs = 30_000) {
    this.initialDelayMs = initialDelayMs;
    this.maxDelayMs = maxDelayMs;
    this.nextDelay = initialDelayMs;
  }

  /** ¿Hay un reintento esperando? */
  get pending(): boolean {
    return this.timer !== null;
  }

  /** Programa `run` tras el retardo actual y duplica el retardo (hasta el máximo). */
  schedule(run: () => void): void {
    this.cancel();
    const delay = this.nextDelay;
    this.nextDelay = Math.min(this.nextDelay * 2, this.maxDelayMs);
    this.timer = setTimeout(() => {
      this.timer = null;
      run();
    }, delay);
  }

  /** Vuelve al retardo inicial (llamar solo cuando la conexión entregó datos). */
  reset(): void {
    this.nextDelay = this.initialDelayMs;
  }

  /** Anula el reintento pendiente, si lo hay. */
  cancel(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}