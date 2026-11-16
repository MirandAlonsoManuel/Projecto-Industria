import { useState, useEffect, useMemo } from 'react';
import type { Camera, CameraProtocol, ROI } from '../../types/index';
import { getCameras, type ApiCamera } from '../../services/cameraApi';
import { useCameraSignal } from '../../hooks/useCameraSignal';
import { useModels } from '../../hooks/useModels';
import { LeftSideBar } from './LeftSidebar';
import { LiveViewer } from './LiveViewer';
import { ResultsHistoryPanel, type ResultHistoryItem } from './ResultsHistoryPanel';
import { useJobStore } from '../../store/jobStore';
import { useToastStore } from '../../store/toastStore';
import { useInferenceConnectionStore } from '../../store/inferenceConnectionStore';
import { JOB_TOAST_KEY, startJobErrorBridge } from '../../store/jobErrorBridge';
import { validateJobStart } from '../../utils/jobErrors';

const FALLBACK_CAMERA: Camera = {
  id: '0',
  name: 'Cámara 0',
  protocol: 'usb2',
  resolution: { width: 1920, height: 1080 },
  fps: 30,
  status: 'disconnected',
  isActive: false,
};

const mockResults: ResultHistoryItem[] = [
  { frameId: 'f-1.004', result: 'ok', timestamp: Date.now() - 5_000 },
  { frameId: 'f-1.003', result: 'ok', timestamp: Date.now() - 12_000 },
  { frameId: 'f-1.002', result: 'nok', timestamp: Date.now() - 20_000 },
  { frameId: 'f-1.001', result: 'ok', timestamp: Date.now() - 33_000 },
  { frameId: 'f-1.000', result: 'ok', timestamp: Date.now() - 40_000 },
];

const KNOWN_PROTOCOLS: CameraProtocol[] = [
  'usb3',
  'usb2',
  'gige',
  'rtsp',
  'http',
  'https',
  'file',
  'ip',
  'other',
];

function normalizeProtocol(type?: string): CameraProtocol {
  if (type === 'usb') return 'usb2';
  return KNOWN_PROTOCOLS.find((p) => p === type) ?? 'other';
}

function apiCameraToCamera(apiCam: ApiCamera, status: Camera['status']): Camera {
  return {
    id: String(apiCam.id),
    name: `Cámara ${apiCam.id}`,
    protocol: normalizeProtocol(apiCam.type),
    resolution: FALLBACK_CAMERA.resolution,
    fps: FALLBACK_CAMERA.fps,
    status,
    isActive: status === 'connected',
  };
}

const SELECT_CLASS =
  'shrink-0 h-8 px-2 rounded-lg border border-[#e2e5ea] bg-white text-[13px] text-[#393939] cursor-pointer focus:outline-[2px] focus:outline-[#2f6fe4] focus:outline-offset-1 disabled:opacity-50 disabled:cursor-not-allowed';

function MainPanel() {
  const [selectedCameraId, setSelectedCameraId] = useState('0');
  const [apiCameras, setApiCameras] = useState<ApiCamera[]>([]);
  const [noCamerasDetected, setNoCamerasDetected] = useState(false);
  const [camerasMessage, setCamerasMessage] = useState<string | null>(null);
  const [activeItem, setActiveItem] = useState<string | null>(null);

  const { models, isLoading: isLoadingModels } = useModels();
  const [selectedModelId, setSelectedModelId] = useState('');

  // T-036: el job vive en un store global; aquí solo se lee y se dispara
  const job = useJobStore((s) => s.job);
  const startJob = useJobStore((s) => s.start);
  const stopJob = useJobStore((s) => s.stop);
  const configureJob = useJobStore((s) => s.configure);

  // T-036: traduce los errores del WebSocket de inferencia en estado del job + toasts.
  // Solo se suscribe (no cambia estado de React), así que es seguro en un efecto.
  useEffect(() => startJobErrorBridge(), []);

  // /signal es solo health check del servidor — sin camera_id
  const { hasSignal } = useCameraSignal();

  // Si el usuario no ha seleccionado nada aún, deriva el modelo activo del default de la API.
  // useMemo evita el patrón setState-en-effect que el React Compiler rechaza.
  const effectiveModelId = useMemo(() => {
    if (selectedModelId) return selectedModelId;
    const def =
      models.find((m) => m.default && m.available && m.enabled) ??
      models.find((m) => m.available && m.enabled);
    return def?.id ?? '';
  }, [selectedModelId, models]);

  const activeApiCamera = apiCameras.find((cam) => cam.id === selectedCameraId) ?? null;
  const effectiveCameraId = activeApiCamera?.id ?? '0';

  const camera: Camera = activeApiCamera
    ? apiCameraToCamera(activeApiCamera, hasSignal ? 'connected' : 'disconnected')
    : { ...FALLBACK_CAMERA, status: hasSignal ? 'connected' : 'disconnected', isActive: hasSignal };

  const toggleInspection = () => {
    const toasts = useToastStore.getState();
    if (job.status === 'running') {
      stopJob();
      toasts.dismissByKey(JOB_TOAST_KEY);
      return;
    }
    // T-036: se valida antes de arrancar; si algo falta, no inicia y se avisa qué corregir
    const problem = validateJobStart({
      modelId: effectiveModelId,
      models,
      connectionStatus: useInferenceConnectionStore.getState().status,
    });
    if (problem) {
      toasts.show({
        key: JOB_TOAST_KEY,
        severity: problem.severity,
        title: problem.title,
        message: problem.message,
        // Un aviso de validación no necesita quedarse fijo
        durationMs: 6_000,
      });
      return;
    }
    toasts.dismissByKey(JOB_TOAST_KEY);
    startJob(effectiveCameraId, effectiveModelId);
  };

  const handleCameraChange = (cameraId: string) => {
    setSelectedCameraId(cameraId);
    configureJob({ cameraId });
  };

  const handleModelChange = (modelId: string) => {
    setSelectedModelId(modelId);
    configureJob({ modelId });
  };

  return (
    <div className="font-inter flex flex-col h-full w-full bg-[#FAF9F9] dark:bg-[#393939] noise-[178,100,5] text-[#393939]">
      {/* {noCamerasDetected && (
        <p className="mx-4 mt-3 rounded-lg bg-[rgba(224,160,32,0.12)] px-3 py-2 text-[13px] font-medium text-[#8a6410]">
          {camerasMessage}
        </p>
      )} */}

      <div className="flex-1 grid grid-cols-[260px_1fr_260px] gap-4 p-4 min-h-0">
        <LeftSideBar
          activeItem = {activeItem}
          setActiveItem = {setActiveItem}
          cameraId={effectiveCameraId}
          naturalWidth={camera.resolution.width}
          naturalHeight={camera.resolution.height}
        />
        <LiveViewer
          activeItem = {activeItem}
          camera={camera}
          cameraId={effectiveCameraId}
          job={job}
          onToggleInspection={toggleInspection}
          // Props nuevas:
          models={models}
          isLoadingModels={isLoadingModels}
          effectiveModelId={effectiveModelId}
          onModelChange={handleModelChange}
          selectedCameraId={selectedCameraId}
          apiCameras={apiCameras}
          onCameraChange={handleCameraChange}
        />
        <ResultsHistoryPanel results={mockResults} />
      </div>
    </div>
  );
}

export { MainPanel };
export default MainPanel;