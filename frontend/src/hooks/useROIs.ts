import { useROIStore } from '../store/roiStore';  // ← el store real, no useROIStore
import { toNormalized, isValidNormalizedRect } from '../utils/roiCoords';

export function useRois(cameraId: string) {
  // Lee directamente del store que ya usa ROICanvas
  const rois       = useROIStore(s => s.rois.filter(r => r.cameraId === cameraId));
  const selectedId = useROIStore(s => s.selectedId);
  const addRoi     = useROIStore(s => s.addRoi);
  const updateRoiDirect = useROIStore(s => s.updateRoiDirect);
  const pushHistory     = useROIStore(s => s.pushHistory);
  const deleteRoi       = useROIStore(s => s.deleteRoi);
  const setLabel        = useROIStore(s => s.setLabel);
  const setEnabled      = useROIStore(s => s.setEnabled);
  const selectRoi       = useROIStore(s => s.selectRoi);
  const undo            = useROIStore(s => s.undo);
  const redo            = useROIStore(s => s.redo);

  // No hay fetchRois todavía — el canvas maneja el estado local

  const createFromCanvas = (
    px: { x: number; y: number; width: number; height: number },
    canvasW: number,
    canvasH: number,
  ) => {
    const norm = toNormalized(px, canvasW, canvasH);
    if (!isValidNormalizedRect(norm)) return;
    addRoi({
      cameraId,
      label: `Zona ${rois.length + 1}`,
      isEnabled: true,
      ...norm,           // ← x, y, width, height planos
    });
  };

  const updateRectFromCanvas = (
    id: string,
    px: { x: number; y: number; width: number; height: number },
    canvasW: number,
    canvasH: number,
  ) => {
    const norm = toNormalized(px, canvasW, canvasH);
    if (!isValidNormalizedRect(norm)) return;
    updateRoiDirect(id, norm);
  };

  return {
    rois, selectedId,
    selectRoi,
    createFromCanvas,
    updateRectFromCanvas,
    patchLabel:  setLabel,
    toggleRoi:   setEnabled,
    removeRoi:   deleteRoi,
    pushHistory,
    undo, redo,
    canUndo: useROIStore.getState().past.length > 0,
    canRedo: useROIStore.getState().future.length > 0,
  };
}