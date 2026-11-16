/**
 * T-27: useInferenceStream — accepts options for conf/iou/inferEveryNFrames/roi/modelId.
 * Reconnects when URL params change.
 * HU-12: estado de la sesión y reconexión solo ante errores recuperables.
 * T-035: publica onopen/onclose/onerror en el store global de conexión.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import type { FrameMetadata, LocalizationDetection, StreamSessionStatus } from '../types';
import {
  CONNECTING_STATUS,
  parseControlMessage,
  shouldReconnect,
  statusFromClose,
} from '../utils/streamSession';
import {
  nextConnectionOwner,
  useInferenceConnectionStore,
} from '../store/inferenceConnectionStore';
import type { WebSocketConnectionState } from './useCameraStream';
import { parseFrameMetadata, splitFrameMessage } from '../utils/frameMetadata';
import { WS_URL } from '../config';
import {
  flushLiveInferenceFrame,
  recordLiveInferenceFrame,
  type LiveInferenceFrame,
} from '../services/lastInferenceEvent';

const WS_BASE = `${WS_URL}/ws/inference-stream`;
const NO_DETECTIONS: LocalizationDetection[] = [];
/** Igual que en useCameraStream: tiempo máximo de caída antes de dejar de reintentar (2 min) */
const MAX_RECONNECT_MS = 120_000;
/** Tras este tiempo abierta, una conexión se considera sana y el siguiente corte reinicia la espera */
const STABLE_CONNECTION_MS = 5_000;

interface InferenceStreamOptions {
  modelId?: string;
  conf?: number;
  iou?: number;
  inferEveryNFrames?: number;
  roi?: { x1: number; y1: number; x2: number; y2: number } | null;
}

interface UseInferenceStreamResult {
  frameUrl: string | null;
  /** Metadata del frame en `frameUrl` (detecciones por clase, score, bbox) */
  frameMetadata: FrameMetadata | null;
  /** Detecciones YOLO incrustadas en el frame más reciente (vacío si aún no llegan) */
  detections: LocalizationDetection[];
  isConnected: boolean;
  /** Mismo significado que en useCameraStream: connecting / connected / reconnecting / disconnected */
  connectionState: WebSocketConnectionState;
  error: string | null;
  /** HU-12: estado de la sesión con código, descripción y si es recuperable */
  session: StreamSessionStatus;
  /** HU-12: vuelve a conectar a mano */
  retry: () => void;
}

/** Frame y su metadata en un solo estado, para que nunca se rendericen desfasados */
interface CurrentFrame {
  url: string;
  metadata: FrameMetadata;
}

function buildWsUrl(cameraId: string, options: InferenceStreamOptions): string {
  const params = new URLSearchParams();
  params.set('camera_id', cameraId);
  if (options.modelId) params.set('model_id', options.modelId);
  if (options.conf !== undefined) params.set('conf', String(options.conf));
  if (options.iou !== undefined) params.set('iou', String(options.iou));
  if (options.inferEveryNFrames !== undefined)
    params.set('infer_every_n_frames', String(options.inferEveryNFrames));
  if (options.roi) {
    params.set('x1', String(options.roi.x1));
    params.set('y1', String(options.roi.y1));
    params.set('x2', String(options.roi.x2));
    params.set('y2', String(options.roi.y2));
  }
  return `${WS_BASE}?${params.toString()}`;
}

/**
 * Análogo a useCameraStream, pero contra /ws/inference-stream: el mismo framing
 * binario [uint32 BE len][JSON][JPEG], donde aquí el JSON trae las detecciones
 * YOLO en vez de venir vacío.
 */
export function useInferenceStream(
  cameraId: string,
  options: InferenceStreamOptions = {}
): UseInferenceStreamResult {
  const [current, setCurrent] = useState<CurrentFrame | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<StreamSessionStatus>(CONNECTING_STATUS);
  const [connectionState, setConnectionState] = useState<WebSocketConnectionState>('connecting');
  /** HU-12: incrementarlo vuelve a correr el efecto, es decir, reconecta desde cero */
  const [attempt, setAttempt] = useState(0);
  const prevUrlRef = useRef<string | null>(null);

  // Serialize URL as dependency so we reconnect when any option changes
  const wsUrl = buildWsUrl(cameraId, options);

  // Datos del análisis en vivo para el "último evento" guardado en IndexedDB.
  const liveEventMetaRef = useRef<Omit<LiveInferenceFrame, 'jpeg' | 'detections'> | null>(null);
  const { modelId, roi } = options;
  useEffect(() => {
    liveEventMetaRef.current = { cameraId, modelId: modelId ?? null, roi: roi ?? null };
  }, [cameraId, modelId, roi]);

  useEffect(() => {
    // Propio de esta ejecución: los eventos de un socket viejo no tocan la conexión nueva
    let disposed = false;
    let ws: WebSocket | null = null;
    let sequence = 0;
    let backoff = 500;
    /** Instante en que empezó la caída actual; null si el stream está sano */
    let downSince: number | null = null;
    let lastStatus: StreamSessionStatus = CONNECTING_STATUS;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    // T-035: esta ejecución publica en el store con su propio id de dueño
    const connection = useInferenceConnectionStore.getState();
    const owner = nextConnectionOwner('inference');

    const updateSession = (status: StreamSessionStatus) => {
      lastStatus = status;
      setSession(status);
    };

    function connect() {
      if (disposed) return;
      reconnectTimer = null;
      const socket = new WebSocket(wsUrl);
      socket.binaryType = 'blob';
      ws = socket;
      updateSession(CONNECTING_STATUS);
      connection.socketConnecting(owner, 'inference');
      /** Instante de apertura de ESTE socket; 0 si nunca abrió */
      let openedAt = 0;

      socket.onopen = () => {
        if (disposed) return;
        openedAt = Date.now();
        setIsConnected(true);
        setConnectionState('connected');
        setError(null);
        connection.socketOpened(owner);
      };

      socket.onmessage = async (event: MessageEvent) => {
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

        const buffer = await event.data.arrayBuffer();
        if (disposed) return;
        const { rawMeta, jpeg } = splitFrameMessage(buffer);
        const metadata = parseFrameMetadata(rawMeta, sequence++);

        const liveMeta = liveEventMetaRef.current;
        if (liveMeta) {
          recordLiveInferenceFrame({ ...liveMeta, jpeg, detections: metadata.detections });
        }

        if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
        const url = URL.createObjectURL(new Blob([jpeg], { type: 'image/jpeg' }));
        prevUrlRef.current = url;
        setCurrent({ url, metadata });
      };

      socket.onerror = () => {
        if (disposed) return;
        setError('Error en la conexión WebSocket de inferencia');
        connection.socketErrored(owner, 'Error en la conexión WebSocket de inferencia');
      };

      socket.onclose = (event: CloseEvent) => {
        if (ws === socket) ws = null;
        if (disposed) return;
        setIsConnected(false);
        // Desconexión: asegura que el último frame analizado quede guardado.
        flushLiveInferenceFrame();
        setCurrent(null);

        // HU-12: el aviso previo del servidor (si lo hubo) decide si se reintenta
        const final = statusFromClose(event.code, lastStatus);
        updateSession(final);
        setError(final.description);
        if (!shouldReconnect(final)) {
          setConnectionState('disconnected');
          connection.socketClosed(owner, final, false);
          return;
        }
        // Solo una conexión que se sostuvo un rato reinicia la espera; si falla recién
        // abierta, la espera crece y al llegar al tope se deja de reintentar.
        if (openedAt > 0 && Date.now() - openedAt >= STABLE_CONNECTION_MS) {
          backoff = 500;
          downSince = null;
        }
        // Mismo tope que useCameraStream: tras 2 min de caída se deja de reintentar
        if (downSince === null) downSince = Date.now();
        if (Date.now() - downSince >= MAX_RECONNECT_MS) {
          setConnectionState('disconnected');
          connection.socketClosed(owner, final, false);
          return;
        }
        setConnectionState('reconnecting');
        connection.socketClosed(owner, final, true);
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 30_000);
      };
    }

    // Arranca tras un tick (StrictMode safety)
    const timer = setTimeout(() => {
      setConnectionState('connecting');
      connect();
    }, 0);

    return () => {
      disposed = true;
      connection.socketReleased(owner);
      clearTimeout(timer);
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      flushLiveInferenceFrame();
      if (ws && ws.readyState < WebSocket.CLOSING) ws.close();
      ws = null;
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current);
        prevUrlRef.current = null;
      }
    };
  }, [wsUrl, attempt]);

  // HU-12: reconexión manual (tras un fin de sesión o un error no recuperable)
  const retry = useCallback(() => {
    setError(null);
    setAttempt((n) => n + 1);
  }, []);

  return {
    frameUrl: current?.url ?? null,
    frameMetadata: current?.metadata ?? null,
    detections: current?.metadata.detections ?? NO_DETECTIONS,
    isConnected,
    connectionState,
    error,
    session,
    retry,
  };
}
