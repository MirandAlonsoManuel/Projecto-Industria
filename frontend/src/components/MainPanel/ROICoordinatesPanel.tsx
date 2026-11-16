import { useROIStore } from '../../store/roiStore';
import { roiToBackendParams } from '../../utils/roiUtils';
import { DeleteX } from '../CommonComponents/Icons/IconCommon';

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
    <section className="bg-white rounded-3xl py-3.5 px-4 flex flex-col gap-0 h-40 dark:bg-[#2E2D2D] dark:text-white">
      <p className="text-[16px] text-center font-medium">
        Zonas de interés (ROI)
      </p>

      {rois.length === 0 && (
        <p className="text-[12px] text-center text-[#9aa3af] dark:text-white">Sin zonas definidas</p>
      )}


      {rois.length != 0 && (
        <table class="table-fixed text-[10px] text-[#BFBFBF] text-center font-semibold ">
           <colgroup>
            <col className="w-[5%]" />
            <col className="w-[5%]" />
            <col className="w-[10%]" />
            <col className="w-[45%]" />
            <col className="w-[2%]" />
          </colgroup>
          <tbody className=''>
            <tr>
              <td>ID</td>
              <td>Color</td>
              <td>Etiqueta</td>
              <td>Coordenadas</td>
            </tr>
          </tbody>
        </table>
      )}

      {rois.length != 0 && (
      <div className={`flex-1 min-h-0 ${rois.length >= 4 ? 'overflow-y-scroll' :''}`}>
      {rois.map((roi) => {
        const nat = { width: naturalWidth, height: naturalHeight };
        const px  = roiToBackendParams(roi, nat);
        const isSelected = roi.id === selectedId;

        return (
          <div key={roi.id} className={`${isSelected ? 'bg-[#F7F7F7] rounded-md border-none dark:bg-[#404040]' : 'border-none'}`}>
            <table class="table-fixed text-[9px] justify-center">
              <colgroup>
                <col className="w-[5%]" />
                <col className="w-[5%]" />
                <col className="w-[10%]" />
                <col className="w-[25%]" />
                <col className="w-[20%]" />
                <col className="w-[1%]" />
              </colgroup>
              <tbody className='text-center pb-0'>
                <tr>
                  <td className=''>ID</td>
                  <td className='border-l border-[#E1E1E1]'><span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ background: roi.color }} /></td>
                  <td className='border-l border-[#E1E1E1]'>{roi.label}</td>
                  <td className='border-l border-[#E1E1E1] pl-0.5'>
                    <div className='flex flex-row gap-x-2 justify-center'>
                      {/* Coordenadas normalizadas */}
                      <div className="grid grid-cols-4 gap-x-1.5 gap-y-0.5 text-[#8b8b8b]">
                        <CoordRow label="x" value={roi.x.toFixed(3)} />
                        <CoordRow label="y" value={roi.y.toFixed(3)} />
                        <CoordRow label="w" value={roi.width.toFixed(3)} />
                        <CoordRow label="h" value={roi.height.toFixed(3)} />
                      </div>
                      <p className='text-[#E1E1E1] pr-1'>| </p>
                      {/* Coordenadas en píxeles (para el backend) */}
                    </div>
                  </td>
                  <td>
                    <div className="border-[#f1f2f4] grid grid-cols-4 gap-x-1.5 gap-y-0.5 text-[#8b8b8b]">
                        <CoordRow label="x1" value={String(px.x1)} />
                        <CoordRow label="y1" value={String(px.y1)} />
                        <CoordRow label="x2" value={String(px.x2)} />
                        <CoordRow label="y2" value={String(px.y2)} />
                      </div>
                  </td>
                  <td>
                      {/* ← AGREGAR este botón */}
                    <button
                      type="button"
                      onClick={() => deleteROI(roi.id)}
                      title="Eliminar zona"
                      className="ml-4 flex items-center justify-center rounded
                                text-[#E29F9C] hover:text-[#d64545] hover:bg-[rgba(214,69,69,0.08)]
                                transition-colors text-[14px] leading-none p-0.5"
                    >
                      <DeleteX></DeleteX>
                    </button></td>
                </tr>
              </tbody>
            </table>
          </div>
        );
      })}
      </div>
      )}
    </section>
  );
}

function CoordRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-row justify-between">
      <span className="inter">{label}:</span>
      <span className="inter font-medium text-[#393939] dark:text-white">{value}</span>
    </div>
  );
}