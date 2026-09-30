/**
 * T-12: FrameBuffer — drop-oldest circular buffer (maxSize=3)
 * T-13: Canvas rAF draw loop, ResizeObserver, Worker integration, bbox overlay
 * T-15: Exponential backoff reconnect
 * T-16: Watchdog for frozen streams
 */
import { useState, useEffect, useRef } from 'react';
import type { LocalizationDetection } from '../types';

const WS_URL = 'ws://127.0.0.1:8000/ws/stream';

// ---------------------------------------------------------------------------
// T-12: Frame buffer
// ---------------------------------------------------------------------------
class FrameBuffer {
  private items: ArrayBuffer[] = [];
  private readonly maxSize: number;

  constructor(maxSize = 3) {
    this.maxSize = maxSize;
  }

  push(item: ArrayBuffer): void {
    if (this.items.length >= this.maxSize) {
      this.items.shift(); // drop oldest
    }
    this.items.push(item);
  }

  pop(): ArrayBuffer | undefined {
    return this.items.shift();
  }
}

// ---------------------------------------------------------------------------
// Detection normalization (shared with inference stream)
// ---------------------------------------------------------------------------
interface RawStreamedDetection {
  class_id?: number;
  classId?: number;
  class_name?: string;
  className?: string;
  confidence?: number;
  bbox?: { x1: number; y1: number; x2: number; y2: number };
}

function normalizeDetections(raw: unknown): LocalizationDetection[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((d): d is RawStreamedDetection => !!d && typeof d === 'object')
    .map((d) => ({
      classId: d.class_id ?? d.classId ?? -1,
      className: d.class_name ?? d.className,
      confidence: d.confidence ?? 0,
      bbox: d.bbox ?? { x1: 0, y1: 0, x2: 0, y2: 0 },
    }));
}

// ---------------------------------------------------------------------------
// Canvas helpers
// ---------------------------------------------------------------------------
interface ContainFitResult {
  dx: number;
  dy: number;
  dw: number;
  dh: number;
  scaleX: number;
  scaleY: number;
}

function computeContainFit(
  canvasW: number,
  canvasH: number,
  imgW: number,
  imgH: number
): ContainFitResult {
  const scale = Math.min(canvasW / imgW, canvasH / imgH);
  const dw = imgW * scale;
  const dh = imgH * scale;
  const dx = (canvasW - dw) / 2;
  const dy = (canvasH - dh) / 2;
  return { dx, dy, dw, dh, scaleX: scale, scaleY: scale };
}

function drawBBoxes(
  ctx: CanvasRenderingContext2D,
  detections: LocalizationDetection[],
  fit: ContainFitResult
): void {
  if (detections.length === 0) return;
  ctx.save();
  for (const det of detections) {
    const { x1, y1, x2, y2 } = det.bbox;
    const rx = fit.dx + x1 * fit.scaleX;
    const ry = fit.dy + y1 * fit.scaleY;
    const rw = (x2 - x1) * fit.scaleX;
    const rh = (y2 - y1) * fit.scaleY;

    ctx.strokeStyle = '#2f6fe4';
    ctx.lineWidth = 2;
    ctx.strokeRect(rx, ry, rw, rh);

    const label = `${det.className ?? `clase ${det.classId}`} ${Math.round(det.confidence * 100)}%`;
    ctx.font = 'bold 11px sans-serif';
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = '#2f6fe4';
    ctx.fillRect(rx, ry - 16, tw + 6, 16);
    ctx.fillStyle = '#fff';
    ctx.fillText(label, rx + 3, ry - 3);
  }
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Hook result
// ---------------------------------------------------------------------------
interface UseCameraStreamResult {
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  isConnected: boolean;
  error: string | null;
  naturalSize: { width: number; height: number } | null;
  displaySize: { width: number; height: number };
  detections: LocalizationDetection[];
}

export function useCameraStream(cameraId: string): UseCameraStreamResult {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [displaySize, setDisplaySize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
  const [detections, setDetections] = useState<LocalizationDetection[]>([]);

  // Mutable refs that must not trigger re-renders
  const frameBuffer = useRef(new FrameBuffer(3));
  const backoffRef = useRef(500);
  const destroyedRef = useRef(false);
  const connectRef = useRef<() => void>(() => {});
  const wsRef = useRef<WebSocket | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef(0);
  const naturalSizeRef = useRef<{ width: number; height: number } | null>(null);
  const detectionsRef = useRef<LocalizationDetection[]>([]);

  // T-13: ResizeObserver — runs once, canvas is always in DOM
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        const w = Math.round(width);
        const h = Math.round(height);
        if (w > 0 && h > 0) {
          canvas.width = w;
          canvas.height = h;
          setDisplaySize({ width: w, height: h });
        }
      }
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  // T-13: rAF draw loop — start once, keep running
  useEffect(() => {
    let cancelled = false;

    async function drawLoop() {
      if (cancelled) return;
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');

      const raw = frameBuffer.current.pop();
      if (raw && canvas && ctx) {
        try {
          const blob = new Blob([raw], { type: 'image/jpeg' });
          const bitmap = await createImageBitmap(blob);

          // Track natural size from first bitmap
          if (!naturalSizeRef.current) {
            const ns = { width: bitmap.width, height: bitmap.height };
            naturalSizeRef.current = ns;
            setNaturalSize(ns);
          }

          const fit = computeContainFit(canvas.width, canvas.height, bitmap.width, bitmap.height);
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(bitmap, fit.dx, fit.dy, fit.dw, fit.dh);
          bitmap.close();

          drawBBoxes(ctx, detectionsRef.current, fit);
        } catch {
          // ignore decode errors
        }
      }

      rafRef.current = requestAnimationFrame(drawLoop);
    }

    rafRef.current = requestAnimationFrame(drawLoop);
    return () => {
      cancelled = true;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, []);

  // T-11 + T-13 + T-15 + T-16: WebSocket + Worker + reconnect + watchdog
  useEffect(() => {
    destroyedRef.current = false;
    backoffRef.current = 500;

    // Worker for frame deserialization
    const worker = new Worker(new URL('../workers/frameDeserializer.ts', import.meta.url), {
      type: 'module',
    });

    worker.onmessage = (event: MessageEvent<{ meta: unknown; jpeg: ArrayBuffer }>) => {
      const { meta, jpeg } = event.data;
      lastFrameAtRef.current = Date.now();

      // Parse detections from meta
      if (meta && typeof meta === 'object') {
        const metaObj = meta as Record<string, unknown>;
        const rawDets = metaObj.detections ?? meta;
        const parsed = normalizeDetections(rawDets);
        detectionsRef.current = parsed;
        setDetections(parsed);
      }

      frameBuffer.current.push(jpeg);
    };

    // T-15: connect function stored in ref to avoid stale closures
    function connect() {
      if (destroyedRef.current) return;

      const ws = new WebSocket(`${WS_URL}?camera_id=${encodeURIComponent(cameraId)}`);
      ws.binaryType = 'blob';
      wsRef.current = ws;

      ws.onopen = () => {
        backoffRef.current = 500;
        setIsConnected(true);
        setError(null);
      };

      ws.onmessage = async (event: MessageEvent) => {
        if (typeof event.data === 'string') {
          try {
            const handshake = JSON.parse(event.data) as {
              connected: boolean;
              description?: string;
            };
            if (!handshake.connected) {
              setError(handshake.description ?? 'No se detectó ninguna cámara.');
            }
          } catch {
            // unknown text message, ignore
          }
          return;
        }
        if (!(event.data instanceof Blob)) return;

        // Transfer ArrayBuffer to worker (zero-copy)
        const buffer = await event.data.arrayBuffer();
        worker.postMessage(buffer, [buffer]);
      };

      ws.onerror = () => setError('Error en la conexión WebSocket');

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        if (!destroyedRef.current) {
          // T-15: exponential backoff
          setTimeout(connectRef.current, backoffRef.current);
          backoffRef.current = Math.min(backoffRef.current * 2, 30_000);
        }
      };
    }

    connectRef.current = connect;

    // Start initial connection after a tick (StrictMode safety)
    const initTimer = setTimeout(connect, 0);

    // T-16: Watchdog — check for frozen stream every second
    const watchdogInterval = setInterval(() => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        if (lastFrameAtRef.current > 0 && Date.now() - lastFrameAtRef.current > 5000) {
          ws.close(); // triggers reconnect via onclose
        }
      }
    }, 1000);

    return () => {
      destroyedRef.current = true;
      clearTimeout(initTimer);
      clearInterval(watchdogInterval);
      worker.terminate();
      const ws = wsRef.current;
      if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
      wsRef.current = null;
    };
  }, [cameraId]);

  return { canvasRef, isConnected, error, naturalSize, displaySize, detections };
}
