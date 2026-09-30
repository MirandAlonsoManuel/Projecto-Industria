import { useState, useEffect, useMemo } from 'react';
import type { Camera, CameraProtocol, ROI, Job, Model } from '../../types/index';
import type { ApiModel } from '../../types';
import { getCameras, type ApiCamera } from '../../services/cameraApi';
import { useCameraSignal } from '../../hooks/useCameraSignal';
import { useModels } from '../../hooks/useModels';
import { LeftSideBar } from './LeftSidebar';
import { LiveViewer } from './LiveViewer';
import { TopBar } from '../Toolbar';
import { ResultsHistoryPanel, type ResultHistoryItem } from './ResultsHistoryPanel';

const FALLBACK_CAMERA: Camera = {
  id: '0',
  name: 'Cámara 0',
  protocol: 'usb2',
  resolution: { width: 1920, height: 1080 },
  fps: 30,
  status: 'disconnected',
  isActive: false,
};

const mockRois: ROI[] = [];

const mockResults: ResultHistoryItem[] = [
  { frameId: 'f-1.004', result: 'ok', timestamp: Date.now() - 5_000 },
  { frameId: 'f-1.003', result: 'ok', timestamp: Date.now() - 12_000 },
  { frameId: 'f-1.002', result: 'nok', timestamp: Date.now() - 20_000 },
  { frameId: 'f-1.001', result: 'ok', timestamp: Date.now() - 33_000 },
  { frameId: 'f-1.000', result: 'ok', timestamp: Date.now() - 40_000 },
];

const TASK_LABELS: Record<string, string> = {
  localization: 'Detección YOLO',
  classification: 'Clasificación',
  ocr: 'OCR',
  anomaly: 'Anomalías',
};

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

// Convierte ApiModel (respuesta de /models) al tipo interno Model usado por la UI
function apiModelToModel(m: ApiModel): Model {
  return {
    id: m.id,
    name: `${TASK_LABELS[m.task] ?? m.task} — ${m.id}`,
    architecture: 'yolov8',
    classes: [],
    confidenceThreshold: 0.25,
    isActive: m.default && m.available && m.enabled,
  };
}

const SELECT_CLASS =
  'shrink-0 h-8 px-2 rounded-lg border border-[#e2e5ea] bg-white text-[13px] text-[#1f2430] cursor-pointer focus:outline-[2px] focus:outline-[#2f6fe4] focus:outline-offset-1 disabled:opacity-50 disabled:cursor-not-allowed';

function MainPanel() {
  const [selectedCameraId, setSelectedCameraId] = useState('0');
  const [apiCameras, setApiCameras] = useState<ApiCamera[]>([]);
  const [noCamerasDetected, setNoCamerasDetected] = useState(false);
  const [camerasMessage, setCamerasMessage] = useState<string | null>(null);

  const { models, isLoading: isLoadingModels } = useModels();
  const [selectedModelId, setSelectedModelId] = useState('');

  const [job, setJob] = useState<Job>({
    id: 'job-01',
    cameraId: '0',
    modelId: '',
    status: 'idle',
  });

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

  useEffect(() => {
    getCameras()
      .then(({ cameras, total, description }) => {
        setApiCameras(cameras);
        setSelectedCameraId(cameras[0]?.id ?? '0');
        setNoCamerasDetected(total === 0);
        setCamerasMessage(total === 0 ? (description ?? 'No se detectaron cámaras.') : null);
      })
      .catch(() => {
        setNoCamerasDetected(true);
        setCamerasMessage('No se pudo consultar el listado de cámaras.');
      });
  }, []);

  const activeApiCamera = apiCameras.find((cam) => cam.id === selectedCameraId) ?? null;
  const effectiveCameraId = activeApiCamera?.id ?? '0';

  const camera: Camera = activeApiCamera
    ? apiCameraToCamera(activeApiCamera, hasSignal ? 'connected' : 'disconnected')
    : { ...FALLBACK_CAMERA, status: hasSignal ? 'connected' : 'disconnected', isActive: hasSignal };

  const activeApiModel = models.find((m) => m.id === effectiveModelId) ?? null;
  const model: Model = activeApiModel
    ? apiModelToModel(activeApiModel)
    : {
        id: effectiveModelId || 'none',
        name: isLoadingModels ? 'Cargando modelos…' : 'Sin modelo',
        architecture: 'yolov8',
        classes: [],
        confidenceThreshold: 0.25,
        isActive: false,
      };

  const toggleInspection = () => {
    setJob((prev) => ({
      ...prev,
      cameraId: effectiveCameraId,
      modelId: effectiveModelId,
      status: prev.status === 'running' ? 'stopped' : 'running',
      startedAt: prev.status === 'running' ? prev.startedAt : Date.now(),
    }));
  };

  const handleCameraChange = (cameraId: string) => {
    setSelectedCameraId(cameraId);
    setJob((prev) => ({ ...prev, cameraId, status: 'idle', startedAt: undefined }));
  };

  const handleModelChange = (modelId: string) => {
    setSelectedModelId(modelId);
    setJob((prev) => ({ ...prev, modelId, status: 'idle', startedAt: undefined }));
  };

  return (
    <div className="font-inter flex flex-col h-full w-full bg-[#f5f6f8] text-[#1f2430]">
      <TopBar
        title={`Panel principal — ${camera.name}`}
        status={camera.status}
        cameraName={camera.name}
        rightSlot={
          <>
            <select
              value={effectiveModelId}
              onChange={(e) => handleModelChange(e.target.value)}
              className={SELECT_CLASS}
              aria-label="Seleccionar modelo"
              disabled={isLoadingModels}
            >
              {models.length > 0 ? (
                models.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available || !m.enabled}>
                    {TASK_LABELS[m.task] ?? m.task} — {m.id}
                    {m.default ? ' ★' : ''}
                  </option>
                ))
              ) : (
                <option value="">{isLoadingModels ? 'Cargando…' : 'Sin modelos'}</option>
              )}
            </select>

            <select
              value={selectedCameraId}
              onChange={(e) => handleCameraChange(e.target.value)}
              className={SELECT_CLASS}
              aria-label="Seleccionar cámara"
            >
              {apiCameras.length > 0 ? (
                apiCameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    Cámara {c.id}
                  </option>
                ))
              ) : (
                <option value="0">{FALLBACK_CAMERA.name}</option>
              )}
            </select>
          </>
        }
      />

      {noCamerasDetected && (
        <p className="mx-4 mt-3 rounded-lg bg-[rgba(224,160,32,0.12)] px-3 py-2 text-[13px] font-medium text-[#8a6410]">
          {camerasMessage}
        </p>
      )}

      <div className="flex-1 grid grid-cols-[260px_1fr_280px] gap-4 p-4 min-h-0">
        <LeftSideBar camera={camera} model={model} rois={mockRois} />
        <LiveViewer
          camera={camera}
          cameraId={effectiveCameraId}
          rois={mockRois}
          job={job}
          onToggleInspection={toggleInspection}
        />
        <ResultsHistoryPanel results={mockResults} />
      </div>
    </div>
  );
}

export { MainPanel };
export default MainPanel;
