import type { Camera, Job } from '../../types/index';
import type { ApiModel } from '../../types';
import { useCameraStream } from '../../hooks/useCameraStream';
import { ButtonCommon } from '../CommonComponents';
import { ROICanvas } from './ROICanvas';
import { TopBar } from '../Toolbar';

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
}: LiveViewerProps) {
  const isInspectionRunning = job.status === 'running';
  const { canvasRef, isConnected, error, displaySize } = useCameraStream(cameraId);

  return (
    <div className="flex flex-col items-center gap-1 min-h-0 mt-10">

      {/* TopBar ahora vive aquí */}
      <TopBar
        title={`Panel principal — ${camera.name}`}
        status={camera.status}
        cameraName={camera.name}
        rightSlot={
          <>
            <select
              value={effectiveModelId}
              onChange={(e) => onModelChange(e.target.value)}
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
              onChange={(e) => onCameraChange(e.target.value)}
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
                <option value="0">{camera.name}</option>
              )}
            </select>
          </>
        }
        camera = {camera}
      />

      {/* Canvas container — igual que antes */}
      <div className="relative w-full aspect-video bg-[#B1B0B0] rounded-[10px] overflow-hidden flex items-center justify-center">
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

      <ButtonCommon
        variant="control"
        isActive={isInspectionRunning}
        onClick={onToggleInspection}
        aria-pressed={isInspectionRunning}
      >
        {isInspectionRunning ? 'Detener' : 'Iniciar'}
      </ButtonCommon>
    </div>
  );
}