/**
 * LiveViewer — canvas-based stream viewer with ROI overlay.
 * Uses useCameraStream (T-13) and ROICanvas (T-18+T-20+T-21+T-22+T-23).
 */
import type { Camera, Job } from '../../types/index';
import { useCameraStream } from '../../hooks/useCameraStream';
import { ButtonCommon } from '../CommonComponents';
import { ROICanvas } from './ROICanvas';

interface LiveViewerProps {
  camera: Camera;
  cameraId: string;
  job: Job;
  onToggleInspection: () => void;
}

export function LiveViewer({ camera, cameraId, job, onToggleInspection }: LiveViewerProps) {
  const isInspectionRunning = job.status === 'running';
  const { canvasRef, isConnected, error, displaySize } = useCameraStream(cameraId);

  return (
    <div className="flex flex-col items-center gap-4 min-h-0">
      {/* Canvas container */}
      <div className="relative w-full flex-1 bg-[#1f2430] rounded-[10px] overflow-hidden flex items-center justify-center">
        {/* Status overlays */}
        {error && <div className="text-sm font-semibold text-[#d64545]">{error}</div>}
        {!isConnected && !error && (
          <div className="text-[13px] text-[#6b7280]">Conectando stream…</div>
        )}

        {/* Canvas — always in DOM so ResizeObserver and rAF loop can attach */}
        <canvas
          ref={canvasRef}
          aria-label={`Stream de ${camera.name}`}
          className="absolute inset-0 w-full h-full"
          style={{ display: 'block' }}
        />

        {/* ROI overlay — only when canvas has real dimensions */}
        {displaySize.width > 0 && (
          <ROICanvas width={displaySize.width} height={displaySize.height} cameraId={cameraId} />
        )}

        {/* T-13 inspection badge */}
        {isInspectionRunning && (
          <div
            className="absolute top-3 right-3 flex items-center gap-1.5 bg-[#d64545] text-white
                       text-[11px] font-bold uppercase tracking-widest rounded-full px-3 py-1"
          >
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
