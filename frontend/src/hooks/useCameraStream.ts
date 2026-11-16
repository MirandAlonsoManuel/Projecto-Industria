/**
 * T-12: FrameBuffer (utils/frameBuffer) — drop-oldest circular buffer (maxSize=3)
 * T-13: Canvas rAF draw loop, ResizeObserver, Worker integration, bbox overlay
 * T-15: Exponential backoff reconnect
 * T-16: Watchdog for frozen streams
 * HU-12: estado de la sesión (connecting/active/stopped/disconnected/error) y
 *        reconexión solo ante errores recuperables
 * T-035: publica onopen/onclose/onerror en el store global de conexión
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { roiToBackendParams, type NormalizedROI, type ROIPixelCoords } from '../utils/roiUtils';
import type { FrameMetadata, StreamSessionStatus } from '../types';
import {
  CONNECTING_STATUS,
  STREAM_FROZEN_CLOSE_CODE,
  parseControlMessage,
  shouldReconnect,
  statusFromClose,
} from '../utils/streamSession';
import {
  nextConnectionOwner,
  useInferenceConnectionStore,
} from '../store/inferenceConnectionStore';
import type { FrameWorkerResult } from '../workers/frameDeserializer';
import { clearDetections, redrawDetections } from '../utils/detectionDrawing';
import { computeContainFit } from '../utils/bboxTransform';
import { FrameBuffer } from '../utils/frameBuffer';
import { WS_URL } from '../config';
import {
  flushLiveInferenceFrame,
  recordLiveInferenceFrame,
  type LiveInferenceFrame,
} from '../services/lastInferenceEvent';

const STREAM_WS_URL = `${WS_URL}/ws/stream`;
const INFERENCE_WS_URL = `${WS_URL}/ws/inference-stream`;
/** T-015: tiempo máximo de caída continua antes de pasar a 'disconnected' y dejar de reintentar (2 min). */
const MAX_RECONNECT_MS = 120_000;

interface CameraStreamOptions {
  /** 'inference' abre /ws/inference-stream y cada frame trae sus detecciones */
  mode?: 'stream' | 'inference';
  modelId?: string;
  conf?: number;
  iou?: number;
  inferEveryNFrames?: number;
  /**
   * ROI normalizado (0–1). El hook lo convierte a píxeles con el tamaño REAL del frame
   * que llega por el stream, no con una resolución supuesta de la cámara.
   */
  roi?: NormalizedROI | null;
}

/** Tras este tiempo abierta, una conexión se considera sana y el siguiente corte reinicia la espera */
const STABLE_CONNECTION_MS = 5_000;

function buildWsUrl(
  cameraId: string,
  options: CameraStreamOptions,
  pixelRoi: ROIPixelCoords | null
): string {
  const params = new URLSearchParams();
  params.set('camera_id', cameraId);

  if (options.mode === 'inference') {
    if (options.modelId) params.set('model_id', options.modelId);
    if (options.conf !== undefined) params.set('conf', String(options.conf));
    if (options.iou !== undefined) params.set('iou', String(options.iou));
    if (options.inferEveryNFrames !== undefined) {
      params.set('infer_every_n_frames', String(options.inferEveryNFrames));
    }
    if (pixelRoi) {
      params.set('x1', String(pixelRoi.x1));
      params.set('y1', String(pixelRoi.y1));
      params.set('x2', String(pixelRoi.x2));
      params.set('y2', String(pixelRoi.y2));
    }
  }

  const base = options.mode === 'inference' ? INFERENCE_WS_URL : STREAM_WS_URL;
  return `${base}?${params.toString()}`;
}

// ---------------------------------------------------------------------------
// Canvas helpers
// ---------------------------------------------------------------------------

/** Último frame pintado: permite repintar video + cajas al redimensionar sin esperar otro frame */
interface DrawnFrame {
  bitmap: ImageBitmap;
  metadata: FrameMetadata;
}

/** Pinta el frame (letterbox) y su capa de detecciones con el tamaño actual del canvas. */
function paintFrame(
  canvas: HTMLCanvasElement,
  overlay: HTMLCanvasElement | null,
  { bitmap, metadata }: DrawnFrame
): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const display = { width: canvas.width, height: canvas.height };
  const frameSize = { width: bitmap.width, height: bitmap.height };

  const fit = computeContainFit(display, frameSize);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, fit.dx, fit.dy, fit.dw, fit.dh);

  // Overlay del MISMO frame: se limpia y redibuja, sin acumular
  if (overlay) {
    redrawDetections(overlay, metadata.detections, frameSize, display, metadata.sourceSize);
  }
}

/** T-015: estado explícito de la conexión WebSocket, legible desde fuera del hook. */
export type WebSocketConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

// ---------------------------------------------------------------------------
// Hook result
// ---------------------------------------------------------------------------
interface UseCameraStreamResult {
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  /** Canvas de la capa de detecciones (se pasa a <DetectionCanvas />) */
  detectionCanvasRef: React.RefObject<HTMLCanvasElement | null>;
  isConnected: boolean;
  connectionState: WebSocketConnectionState;
  error: string | null;
  naturalSize: { width: number; height: number } | null;
  displaySize: { width: number; height: number };
  /**
   * Metadata del frame que se está mostrando AHORA (detecciones por clase, score, bbox).
   * Se actualiza en el mismo paso en que se pinta el frame; null si no hay stream.
   */
  frameMetadata: FrameMetadata | null;
  /** HU-12: estado de la sesión con código, descripción y si es recuperable */
  session: StreamSessionStatus;
  /** HU-12: vuelve a conectar a mano (tras un fin de sesión o un error no recuperable) */
  retry: () => void;
}

export function useCameraStream(
  cameraId: string,
  options: CameraStreamOptions = {}
): UseCameraStreamResult {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const detectionCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<WebSocketConnectionState>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [displaySize, setDisplaySize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
  const [frameMetadata, setFrameMetadata] = useState<FrameMetadata | null>(null);
  const [session, setSession] = useState<StreamSessionStatus>(CONNECTING_STATUS);

  // Mutable refs that must not trigger re-renders
  const frameBuffer = useRef(new FrameBuffer(3));
  const backoffRef = useRef(500);
  /** T-015: instante en que empezó la caída actual; null si el stream está sano. */
  const downSinceRef = useRef<number | null>(null);
  const connectRef = useRef<() => void>(() => {});
  const wsRef = useRef<WebSocket | null>(null);
  /** HU-12: último estado recibido; decide qué pasa al cerrarse el socket */
  const sessionRef = useRef<StreamSessionStatus>(CONNECTING_STATUS);
  const rafRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef(0);
  const naturalSizeRef = useRef<{ width: number; height: number } | null>(null);
  const { modelId, roi } = options;
  // El ROI se manda en píxeles del frame real. Si aún no llegó ningún frame no se
  // conoce su tamaño: se conecta sin ROI y, al llegar el primero, se reconecta con él.
  const pixelRoi = useMemo(
    () => (roi && naturalSize ? roiToBackendParams(roi, naturalSize) : null),
    [roi, naturalSize]
  );
  const wsUrl = buildWsUrl(cameraId, options, pixelRoi);
  const lastDrawnRef = useRef<DrawnFrame | null>(null);

  // Datos del análisis en vivo para el "último evento". null fuera del modo inferencia:
  // el stream sin modelo no es un evento de inferencia y no debe pisar el guardado.
  const liveEventMetaRef = useRef<Omit<LiveInferenceFrame, 'jpeg' | 'detections'> | null>(null);
  const isInference = options.mode === 'inference';
  const endpoint = isInference ? 'inference' : 'stream';
  useEffect(() => {
    liveEventMetaRef.current = isInference
      ? { cameraId, modelId: modelId ?? null, roi: pixelRoi }
      : null;
  }, [cameraId, isInference, modelId, pixelRoi]);

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
          // Cambiar el tamaño borra el canvas: se repinta el último frame con la nueva escala
          if (lastDrawnRef.current) {
            paintFrame(canvas, detectionCanvasRef.current, lastDrawnRef.current);
          }
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

      const frame = frameBuffer.current.pop();
      if (frame && canvas && ctx) {
        try {
          const blob = new Blob([frame.jpeg], { type: 'image/jpeg' });
          const bitmap = await createImageBitmap(blob);

          const size = naturalSizeRef.current;
          if (!size || size.width !== bitmap.width || size.height !== bitmap.height) {
            const ns = { width: bitmap.width, height: bitmap.height };
            naturalSizeRef.current = ns;
            setNaturalSize(ns);
          }

          const drawn: DrawnFrame = { bitmap, metadata: frame.metadata };
          paintFrame(canvas, detectionCanvasRef.current, drawn);
          lastDrawnRef.current?.bitmap.close();
          lastDrawnRef.current = drawn;
          setFrameMetadata(frame.metadata);
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
      lastDrawnRef.current?.bitmap.close();
      lastDrawnRef.current = null;
    };
  }, []);

  // T-11 + T-13 + T-15 + T-16: WebSocket + Worker + reconnect + watchdog
  useEffect(() => {
    /** Olvida el último frame pintado y limpia la capa de detecciones */
    const resetDrawnFrame = () => {
      lastDrawnRef.current?.bitmap.close();
      lastDrawnRef.current = null;
      if (detectionCanvasRef.current) clearDetections(detectionCanvasRef.current);
    };

    // Propio de esta ejecución del efecto: los eventos de un socket viejo (de antes
    // de cambiar de URL o desmontar) no deben tocar la conexión nueva.
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    // T-035: esta ejecución publica en el store con su propio id de dueño
    const connection = useInferenceConnectionStore.getState();
    const owner = nextConnectionOwner(endpoint);

    backoffRef.current = 500;
    downSinceRef.current = null;
    lastFrameAtRef.current = 0;
    frameBuffer.current.clear();
    resetDrawnFrame();

    const updateSession = (status: StreamSessionStatus) => {
      sessionRef.current = status;
      setSession(status);
    };

    // Worker for frame deserialization
    const worker = new Worker(new URL('../workers/frameDeserializer.ts', import.meta.url), {
      type: 'module',
    });

    worker.onmessage = (event: MessageEvent<FrameWorkerResult>) => {
      const { metadata, jpeg } = event.data;
      lastFrameAtRef.current = Date.now();
      frameBuffer.current.push({ jpeg, metadata });

      const liveMeta = liveEventMetaRef.current;
      if (liveMeta) {
        recordLiveInferenceFrame({ ...liveMeta, jpeg, detections: metadata.detections });
      }
    };

    // T-15: connect function stored in ref to avoid stale closures
    function connect() {
      if (disposed) return;
      reconnectTimer = null;

      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'blob';
      wsRef.current = ws;
      // HU-12: cada intento empieza en connecting; pasa a active con la bienvenida
      updateSession(CONNECTING_STATUS);
      connection.socketConnecting(owner, endpoint);
      /** Instante de apertura de ESTE socket; 0 si nunca abrió */
      let openedAt = 0;

      ws.onopen = () => {
        if (disposed) return;
        openedAt = Date.now();
        // T-015: la conexión nueva aún no ha dado frames; sin esto el watchdog (T-16)
        // usa la hora del último frame de la conexión anterior y la cierra al instante.
        lastFrameAtRef.current = 0;
        frameBuffer.current.clear(); // T-015: volvió la conexión; descarta frames viejos del corte
        setIsConnected(true);
        setConnectionState('connected');
        setError(null);
        connection.socketOpened(owner);
      };

      ws.onmessage = async (event: MessageEvent) => {
        if (disposed) return;
        if (typeof event.data === 'string') {
          // HU-12: bienvenida, aviso de fin o error → estado de la sesión
          const status = parseControlMessage(event.data);
          if (status) {
            updateSession(status);
            setError(status.state === 'active' ? null : status.description);
          }
          return;
        }
        if (!(event.data instanceof Blob)) return;

        // Transfer ArrayBuffer to worker (zero-copy)
        const buffer = await event.data.arrayBuffer();
        if (disposed) return;
        worker.postMessage(buffer, [buffer]);
      };

      ws.onerror = () => {
        if (disposed) return;
        setError('Error en la conexión WebSocket');
        connection.socketErrored(owner, 'Error en la conexión WebSocket');
      };

      ws.onclose = (event: CloseEvent) => {
        if (wsRef.current === ws) wsRef.current = null;
        if (disposed) return;
        setIsConnected(false);
        // Desconexión: asegura que el último frame analizado quede guardado.
        flushLiveInferenceFrame();
        // Sin stream no se deben quedar cajas ni datos congelados del último frame
        resetDrawnFrame();
        setFrameMetadata(null);

        // HU-12: el aviso previo del servidor (si lo hubo) decide si se reintenta
        const final = statusFromClose(event.code, sessionRef.current);
        updateSession(final);
        setError(final.description);
        if (!shouldReconnect(final)) {
          // Fin intencional o error no recuperable: se espera a que el usuario reintente
          setConnectionState('disconnected');
          connection.socketClosed(owner, final, false);
          return;
        }

        // Solo una conexión que se sostuvo un rato reinicia la espera. Si falla recién
        // abierta (p. ej. un error que se repite igual en cada intento), la espera crece
        // y al llegar al tope se deja de reintentar, en vez de insistir cada 500 ms.
        if (openedAt > 0 && Date.now() - openedAt >= STABLE_CONNECTION_MS) {
          backoffRef.current = 500;
          downSinceRef.current = null;
        }

        // T-015: cuenta la caída desde el primer cierre; si supera el tope, se rinde
        if (downSinceRef.current === null) downSinceRef.current = Date.now();
        if (Date.now() - downSinceRef.current >= MAX_RECONNECT_MS) {
          setConnectionState('disconnected');
          connection.socketClosed(owner, final, false);
          return;
        }
        // T-15: exponential backoff
        setConnectionState('reconnecting');
        connection.socketClosed(owner, final, true);
        reconnectTimer = setTimeout(connect, backoffRef.current);
        backoffRef.current = Math.min(backoffRef.current * 2, 30_000);
      };
    }

    connectRef.current = connect;

    // Start initial connection after a tick (StrictMode safety)
    const initTimer = setTimeout(() => {
      setConnectionState('connecting');
      connect();
    }, 0);

    // T-16: Watchdog — check for frozen stream every second
    const watchdogInterval = setInterval(() => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        if (lastFrameAtRef.current > 0 && Date.now() - lastFrameAtRef.current > 5000) {
          // HU-12: código propio para que onclose lo reporte como STREAM_FROZEN y reintente
          ws.close(STREAM_FROZEN_CLOSE_CODE, 'STREAM_FROZEN');
        }
      }
    }, 1000);

    return () => {
      disposed = true;
      connection.socketReleased(owner);
      clearTimeout(initTimer);
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      clearInterval(watchdogInterval);
      worker.terminate();
      flushLiveInferenceFrame();
      const ws = wsRef.current;
      if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
      wsRef.current = null;
    };
  }, [wsUrl, endpoint]);

  // HU-12: reconexión manual; no hace nada si ya hay un socket abierto o abriéndose
  const retry = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState < WebSocket.CLOSING) return;
    backoffRef.current = 500;
    downSinceRef.current = null;
    setConnectionState('connecting');
    setError(null);
    connectRef.current();
  }, []);

  return {
    canvasRef,
    detectionCanvasRef,
    isConnected,
    connectionState,
    error,
    naturalSize,
    displaySize,
    frameMetadata,
    session,
    retry,
  };
}
