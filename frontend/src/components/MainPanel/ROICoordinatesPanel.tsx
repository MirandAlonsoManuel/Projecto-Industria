import { useROIStore } from '../../store/roiStore';
import { roiToBackendParams } from '../../utils/roiUtils';

interface ROICoordinatesPanelProps {
  cameraId: string;
  /** Tamaño natural del frame de la cámara para convertir a píxeles */
  naturalWidth?:  number;
  naturalHeight?: number;
}

export function ROICoordinatesPanel({
  cameraId,
  naturalWidth  = 1920,
  naturalHeight = 1080,
}: ROICoordinatesPanelProps) {
  const allRois = useROIStore(s => s.rois);           // referencia estable
  const rois    = allRois.filter(r => r.cameraId === cameraId);  // fuera del store
  const selectedId = useROIStore(s => s.selectedId);
  const undo = useROIStore(s => s.undo);
  const redo = useROIStore(s => s.redo);
  const canUndo = useROIStore(s => s.past.length > 0);
  const canRedo = useROIStore(s => s.future.length > 0);
  const deleteROI = useROIStore(s => s.deleteRoi);

  return (
    <section className="bg-white border border-[#e2e5ea] rounded-2xl py-3.5 px-4 flex flex-col gap-2 max-h-[60vh]">
      <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280]">
        Coordenadas ROI
      </p>

      {rois.length === 0 && (
        <p className="text-[12px] text-[#9aa3af]">Sin zonas definidas</p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={undo}
          disabled={!canUndo}
          title="Deshacer (Ctrl+Z)"
          className="flex-1 flex items-center justify-center gap-1 h-7 rounded-lg border
               border-[#e2e5ea] text-[12px] text-[#1f2430] bg-white
               disabled:opacity-40 disabled:cursor-not-allowed
               hover:enabled:bg-[#f5f6f8] transition-colors"
        >
          ↩ Deshacer
        </button>
        <button
          type="button"
          onClick={redo}
          disabled={!canRedo}
          title="Rehacer (Ctrl+Y)"
          className="flex-1 flex items-center justify-center gap-1 h-7 rounded-lg border
               border-[#e2e5ea] text-[12px] text-[#1f2430] bg-white
               disabled:opacity-40 disabled:cursor-not-allowed
               hover:enabled:bg-[#f5f6f8] transition-colors"
        >
          ↪ Rehacer
        </button>
      </div>

      {rois.map((roi) => {
        const nat = { width: naturalWidth, height: naturalHeight };
        const px  = roiToBackendParams(roi, nat);
        const isSelected = roi.id === selectedId;

        return (
          <div
            key={roi.id}
            className={`rounded-lg border px-3 py-2 text-[12px] transition-colors ${
              isSelected
                ? 'border-[#2f6fe4] bg-[rgba(47,111,228,0.06)]'
                : 'border-[#f1f2f4] bg-[#fafafa]'
            }`}
          >
            {/* Etiqueta + dot de color */}
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: roi.color }} />
              <span className="font-semibold text-[#1f2430] truncate flex-1">{roi.label}</span>
              {!roi.isEnabled && (
                <span className="text-[10px] text-[#9aa3af]">Desactivada</span>
              )}

              {/* ← AGREGAR este botón */}
              <button
                type="button"
                onClick={() => deleteROI(roi.id)}
                title="Eliminar zona"
                className="ml-auto w-5 h-5 flex items-center justify-center rounded
                          text-[#9aa3af] hover:text-[#d64545] hover:bg-[rgba(214,69,69,0.08)]
                          transition-colors text-[14px] leading-none"
              >
                ×
              </button>
            </div>

            {/* Coordenadas normalizadas */}
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[#6b7280]">
              <CoordRow label="x" value={roi.x.toFixed(3)} />
              <CoordRow label="y" value={roi.y.toFixed(3)} />
              <CoordRow label="w" value={roi.width.toFixed(3)} />
              <CoordRow label="h" value={roi.height.toFixed(3)} />
            </div>

            {/* Coordenadas en píxeles (para el backend) */}
            <div className="mt-1.5 pt-1.5 border-t border-[#f1f2f4] grid grid-cols-2 gap-x-3 gap-y-0.5 text-[#9aa3af]">
              <CoordRow label="x1" value={String(px.x1)} />
              <CoordRow label="y1" value={String(px.y1)} />
              <CoordRow label="x2" value={String(px.x2)} />
              <CoordRow label="y2" value={String(px.y2)} />
            </div>
          </div>
        );
      })}
    </section>
  );
}

function CoordRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="font-mono">{label}:</span>
      <span className="font-mono font-medium text-[#1f2430]">{value}</span>
    </div>
  );
}