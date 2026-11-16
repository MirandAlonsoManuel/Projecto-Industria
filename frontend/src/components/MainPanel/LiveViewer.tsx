import type { Camera, Job } from '../../types/index';
import type { ApiModel } from '../../types';
import { useCameraStream } from '../../hooks/useCameraStream';
import { useMemo } from 'react';
import { useROIStore } from '../../store/roiStore';
import { ButtonCommon } from '../CommonComponents';
import { ROICanvas } from './ROICanvas';
import { TopBar } from '../Toolbar';
import { ROICoordinatesPanel } from './ROICoordinatesPanel';
import { MenuOptions } from './MenuOptions';
import { DetectionCanvas } from './DetectionCanvas';
import { StreamSessionNotice } from './StreamSessionNotice';
import { useJobStore } from '../../store/jobStore';
import { retryJob } from '../../store/jobErrorBridge';

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
  // T-036: pausa por error recuperable y último error del job
  const jobPaused = useJobStore((s) => s.paused);
  const jobError = useJobStore((s) => s.error);
  const rois = useROIStore((s) => s.rois);

  // ROI normalizado (0–1); useCameraStream lo pasa a píxeles con el tamaño real del frame.
  // (Antes se usaba camera.resolution, un 1920×1080 fijo, y el ROI salía de la imagen.)
  const activeRoi = rois.find((roi) => roi.cameraId === cameraId && roi.isEnabled);
  const roiX = activeRoi?.x;
  const roiY = activeRoi?.y;
  const roiW = activeRoi?.width;
  const roiH = activeRoi?.height;
  const streamRoi = useMemo(
    () =>
      roiX !== undefined && roiY !== undefined && roiW !== undefined && roiH !== undefined
        ? { x: roiX, y: roiY, width: roiW, height: roiH }
        : null,
    [roiX, roiY, roiW, roiH]
  );

  // El stream de inferencia en vivo solo devuelve detecciones de modelos de localización
  const jobModel = models.find((m) => m.id === job.modelId);
  const isDetectionModel = jobModel?.task === 'localization';
  const isLiveInference = isInspectionRunning && isDetectionModel;

  const streamOptions = useMemo(
    () =>
      isLiveInference
        ? {
            mode: 'inference' as const,
            modelId: job.modelId,
            roi: streamRoi,
          }
        : {
            mode: 'stream' as const,
          },
    [isLiveInference, job.modelId, streamRoi]
  );

  const { canvasRef, detectionCanvasRef, displaySize, session, connectionState, retry } =
    useCameraStream(cameraId, streamOptions);

  return (
    <div className="flex flex-col items-center gap-3 min-h-0 mt-10">

      {/* TopBar ahora vive aquí */}
      {/* T-035: el indicador de conexión lo toma TopBar del store WS (sin /signal) */}
      <TopBar
        cameraName={camera.name}
        job={job}
        onToggleInspection={onToggleInspection}
      />

      {/* Canvas container — igual que antes */}
      <div className="relative w-full aspect-video bg-[#ffffff] dark:bg-[#6D6D6D] rounded-[10px] overflow-hidden flex items-center justify-center">
        {/* HU-12: estado de la sesión (conectando, detenida, desconectada o error) */}
        <StreamSessionNotice session={session} connectionState={connectionState} onRetry={retry} />

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
        {/* T-036: "activa" solo si de verdad está inspeccionando; si reconecta, "en pausa" */}
        {isInspectionRunning && !jobPaused && (
          <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-[#d64545] text-white text-[11px] font-bold uppercase tracking-widest rounded-full px-3 py-1">
            <span className="block w-2 h-2 rounded-full bg-white opacity-90 animate-pulse" />
            Inspección activa
          </div>
        )}
        {isInspectionRunning && jobPaused && (
          <div
            role="status"
            className="absolute top-3 right-3 flex items-center gap-1.5 bg-[#e0a020] text-white text-[11px] font-bold uppercase tracking-widest rounded-full px-3 py-1"
          >
            <span className="block w-2 h-2 rounded-full bg-white opacity-90" />
            Inspección en pausa
          </div>
        )}
        {/* T-036: el job se detuvo por un error; queda visible hasta reintentar o reconfigurar */}
        {job.status === 'error' && jobError && (
          <div
            role="alert"
            className="absolute bottom-3 left-1/2 z-10 flex max-w-[90%] -translate-x-1/2 items-center gap-3 rounded-xl bg-white/95 px-4 py-2 shadow-lg dark:bg-[#2E2D2D]/95"
          >
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-[#d64545]">
                Inspección detenida: {jobError.title}
              </p>
              <p className="text-[12px] text-[#6b7280] dark:text-[#d1d5db]">{jobError.message}</p>
            </div>
            <ButtonCommon variant="secondary" size="large" onClick={retryJob}>
              Reintentar
            </ButtonCommon>
          </div>
        )}
      </div>
      {activeItem &&(
        <MenuOptions
          cameraId={cameraId}
          naturalWidth={naturalWidth}
          naturalHeight={naturalHeight}
          menuOptionSelected={activeItem}
        />
      )}
    </div>
  );
}