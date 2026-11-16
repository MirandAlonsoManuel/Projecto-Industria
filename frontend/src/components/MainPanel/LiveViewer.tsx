import type { Camera, Job } from '../../types/index';
import type { ApiModel } from '../../types';
import { useCameraStream } from '../../hooks/useCameraStream';
import { useROIStore } from '../../store/roiStore';
import { roiToBackendParams, type ROIPixelCoords } from '../../utils/roiUtils';
import { nextSnapshot, type Snapshot } from '../../utils/roiSnapshot';
import { ButtonCommon } from '../CommonComponents';
import { ROICanvas } from './ROICanvas';
import { TopBar } from '../Toolbar';
import { ROICoordinatesPanel } from './ROICoordinatesPanel';
import { MenuOptions } from './MenuOptions';
import { DetectionCanvas } from './DetectionCanvas';
import { useMemo, useState } from 'react';

interface LiveViewerProps {
  camera: Camera;
  cameraId: string;
  job: Job;
  onToggleInspection: () => void;
  // Props nuevas para el TopBar
  models: ApiModel[];
  isLoadingModels: boolean;
  effectiveModelId: string;
  onModelChange: (modelId: string) => void;
  selectedCameraId: string;
  apiCameras: { id: string }[];
  onCameraChange: (cameraId: string) => void;
  naturalWidth?: number;
  naturalHeight?: number;
  activeItem: string | null;
}

const SELECT_CLASS =
  'shrink-0 h-8 px-2 rounded-lg border border-[#e2e5ea] bg-white text-[13px] text-[#393939] cursor-pointer focus:outline-[2px] focus:outline-[#2f6fe4] focus:outline-offset-1 disabled:opacity-50 disabled:cursor-not-allowed';

const TASK_LABELS: Record<string, string> = {
  localization: 'Detección YOLO',
  classification: 'Clasificación',
  ocr: 'OCR',
  anomaly: 'Anomalías',
};

export function LiveViewer({
  camera,
  cameraId,
  job,
  onToggleInspection,
  models,
  isLoadingModels,
  effectiveModelId,
  onModelChange,
  selectedCameraId,
  apiCameras,
  onCameraChange,
  naturalWidth,
  naturalHeight,
  activeItem,
}: LiveViewerProps) {
  const isInspectionRunning = job.status === 'running';
  const rois = useROIStore((s) => s.rois);

  // HU-11: tamaño REAL del frame, medido por el hook al decodificar el primer frame del
  // stream (el backend envía el frame completo, sin reescalar). `camera.resolution` es un
  // valor fijo de 1920×1080 y solo se usa como respaldo hasta que llega ese primer frame.
  const [frameSize, setFrameSize] = useState<{ width: number; height: number } | null>(null);
  const roiBaseWidth = frameSize?.width ?? camera.resolution.width;
  const roiBaseHeight = frameSize?.height ?? camera.resolution.height;

  const streamRoi = useMemo(() => {
    const activeRoi = rois.find((roi) => roi.cameraId === cameraId && roi.isEnabled);
    if (!activeRoi) return null;
    return roiToBackendParams(activeRoi, { width: roiBaseWidth, height: roiBaseHeight });
  }, [rois, cameraId, roiBaseWidth, roiBaseHeight]);

  // El stream de inferencia en vivo solo devuelve detecciones de modelos de localización
  const jobModel = models.find((m) => m.id === job.modelId);
  const isDetectionModel = jobModel?.task === 'localization';
  const isLiveInference = isInspectionRunning && isDetectionModel;

  // HU-11: el ROI va en la URL del WebSocket, así que moverlo durante la inspección
  // reconectaba el stream en cada cambio. Se fija al iniciar; los cambios aplican al
  // siguiente inicio. Se ajusta durante el render (patrón de React) para no mostrar un
  // render intermedio con el ROI sin fijar.
  const [roiSnapshot, setRoiSnapshot] = useState<Snapshot<ROIPixelCoords | null>>(null);
  const nextRoiSnapshot = nextSnapshot(roiSnapshot, isLiveInference, streamRoi);
  if (nextRoiSnapshot !== roiSnapshot) {
    setRoiSnapshot(nextRoiSnapshot);
  }
  const inferenceRoi = nextRoiSnapshot ? nextRoiSnapshot.value : streamRoi;

  const streamOptions = useMemo(
    () =>
      isLiveInference
        ? {
            mode: 'inference' as const,
            modelId: job.modelId,
            roi: inferenceRoi,
          }
        : {
            mode: 'stream' as const,
          },
    [isLiveInference, job.modelId, inferenceRoi]
  );

  const { canvasRef, detectionCanvasRef, isConnected, error, displaySize, naturalSize } =
    useCameraStream(cameraId, streamOptions);

  // HU-11: guarda el tamaño real del frame para convertir el ROI con él. Se ajusta durante
  // el render (patrón de React para derivar estado) porque el hook se llama después de
  // calcular streamRoi y no se puede leer su resultado antes.
  if (
    naturalSize &&
    (frameSize?.width !== naturalSize.width || frameSize?.height !== naturalSize.height)
  ) {
    setFrameSize(naturalSize);
  }

  return (
    <div className="flex flex-col items-center gap-3 min-h-0 mt-10">

      {/* TopBar ahora vive aquí */}
      <TopBar
        status={camera.status}
        cameraName={camera.name}
        job={job}
        onToggleInspection={onToggleInspection}
      />

      {/* Canvas container — igual que antes */}
      <div className="relative w-full aspect-video bg-[#ffffff] dark:bg-[#6D6D6D] rounded-[10px] overflow-hidden flex items-center justify-center">
        {error && <div className="text-sm font-semibold text-[#d64545]">{error}</div>}
        {!isConnected && !error && (
          <div className="text-[13px] text-[#6b7280]">Conectando stream…</div>
        )}
        <canvas
          ref={canvasRef}
          aria-label={`Stream de ${camera.name}`}
          className="absolute inset-0 w-full h-full"
          style={{ display: 'block' }}
        />
        <DetectionCanvas ref={detectionCanvasRef} />
        {displaySize.width > 0 && (
          <ROICanvas width={displaySize.width} height={displaySize.height} cameraId={cameraId} />
        )}
        {isInspectionRunning && (
          <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-[#d64545] text-white text-[11px] font-bold uppercase tracking-widest rounded-full px-3 py-1">
            <span className="block w-2 h-2 rounded-full bg-white opacity-90 animate-pulse" />
            Inspección activa
          </div>
        )}
      </div>
      {activeItem &&(
        <MenuOptions
          cameraId={cameraId}
          naturalWidth={frameSize?.width ?? naturalWidth}
          naturalHeight={frameSize?.height ?? naturalHeight}
          menuOptionSelected={activeItem}
        />
      )}
    </div>
  );
}