// Función que permite guardar las coordenadas del ROI.
import { useEffect, useRef } from 'react';
import { useROIStore } from '../../store/roiStore';
import type { StoredROI } from '../../store/roiStore';

interface ROICanvasProps {
  width: number;
  height: number;
  cameraId: string;
}

const HANDLE_SIZE = 8;
const MIN_PX = 10; // Tamaño mínimo en píxeles para crear un ROI
const MIN_NORM = 0.02; // Tamaño mínimo normalizado

// Funciones auxiliares para la detección de colisiones y manipulación de los manejadores de las ROI.
function hitTest(roi: StoredROI, nx: number, ny: number): boolean {
  return nx >= roi.x && nx <= roi.x + roi.width && ny >= roi.y && ny <= roi.y + roi.height;
}

type HandleIndex = 0 | 1 | 2 | 3; // Superior izquierda, superior derecha, inferior derecha, inferior izquierda

function getHandleNorm(roi: StoredROI, handle: HandleIndex): { hx: number; hy: number } {
  const corners: [number, number][] = [
    [roi.x, roi.y],
    [roi.x + roi.width, roi.y],
    [roi.x + roi.width, roi.y + roi.height],
    [roi.x, roi.y + roi.height],
  ];
  const [hx, hy] = corners[handle];
  return { hx, hy };
}

function hitTestHandle(
  roi: StoredROI,
  nx: number,
  ny: number,
  pxWidth: number,
  pxHeight: number
): HandleIndex | null {
  const hSizeNx = HANDLE_SIZE / pxWidth;
  const hSizeNy = HANDLE_SIZE / pxHeight;
  for (let i = 0; i < 4; i++) {
    const { hx, hy } = getHandleNorm(roi, i as HandleIndex);
    if (Math.abs(nx - hx) <= hSizeNx && Math.abs(ny - hy) <= hSizeNy) {
      return i as HandleIndex;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Dibujo del canvas
// ---------------------------------------------------------------------------
function redrawCanvas(
  canvas: HTMLCanvasElement,
  rois: StoredROI[],
  selectedId: string | null,
  cameraId: string,
  previewRect: NormRect | null
): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  const visible = rois.filter((r) => r.cameraId === cameraId);

  for (const roi of visible) {
    const px = roi.x * w;
    const py = roi.y * h;
    const pw = roi.width * w;
    const ph = roi.height * h;
    const isSelected = roi.id === selectedId;

    // Relleno de la zona
    ctx.fillStyle = hexToRgba(roi.color, 0.12);
    ctx.fillRect(px, py, pw, ph);

    // Borde de la zona
    ctx.strokeStyle = roi.color;
    ctx.lineWidth = isSelected ? 2.5 : 1.5;
    if (isSelected) {
      ctx.setLineDash([]);
    } else {
      ctx.setLineDash([]);
    }
    ctx.strokeRect(px, py, pw, ph);

    // Etiqueta de la zona
    if (roi.label) {
      ctx.font = 'bold 11px sans-serif';
      const tw = ctx.measureText(roi.label).width;
      ctx.fillStyle = roi.color;
      ctx.fillRect(px, py - 16, tw + 6, 16);
      ctx.fillStyle = '#fff';
      ctx.fillText(roi.label, px + 3, py - 3);
    }

    // Manejadores de las esquinas cuando el ROI está seleccionado
    if (isSelected) {
      ctx.fillStyle = '#fff';
      ctx.strokeStyle = roi.color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
      const corners: [number, number][] = [
        [px, py],
        [px + pw, py],
        [px + pw, py + ph],
        [px, py + ph],
      ];
      for (const [cx, cy] of corners) {
        ctx.fillRect(cx - HANDLE_SIZE / 2, cy - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
        ctx.strokeRect(cx - HANDLE_SIZE / 2, cy - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
      }
    }
  }

  // Vista previa mientras se dibuja un ROI nuevo
  if (previewRect) {
    const px = previewRect.x * w;
    const py = previewRect.y * h;
    const pw = previewRect.width * w;
    const ph = previewRect.height * h;
    ctx.strokeStyle = '#2f6fe4';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.strokeRect(px, py, pw, ph);
    ctx.fillStyle = 'rgba(47, 111, 228, 0.08)';
    ctx.fillRect(px, py, pw, ph);
    ctx.setLineDash([]);
  }
}

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ---------------------------------------------------------------------------
// Tipos para controlar la interacción
// ---------------------------------------------------------------------------
interface NormRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

type DragMode =
  | { kind: 'none' }
  | { kind: 'drawing'; startNx: number; startNy: number }
  | {
      kind: 'moving';
      roiId: string;
      startNx: number;
      startNy: number;
      origX: number;
      origY: number;
    }
  | { kind: 'resizing'; roiId: string; handle: HandleIndex; origRoi: StoredROI };

// ---------------------------------------------------------------------------
// Componente
// ---------------------------------------------------------------------------
export function ROICanvas({ width, height, cameraId }: ROICanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dragRef = useRef<DragMode>({ kind: 'none' });
  const previewRef = useRef<NormRect | null>(null);

  const rois = useROIStore((s) => s.rois);
  const selectedId = useROIStore((s) => s.selectedId);
  const selectRoi = useROIStore((s) => s.selectRoi);
  const addRoi = useROIStore((s) => s.addRoi);
  const updateRoiDirect = useROIStore((s) => s.updateRoiDirect);
  const pushHistory = useROIStore((s) => s.pushHistory);
  const deleteRoi = useROIStore((s) => s.deleteRoi);
  const setLabel = useROIStore((s) => s.setLabel);
  const setEnabled = useROIStore((s) => s.setEnabled);
  const undo = useROIStore((s) => s.undo);
  const redo = useROIStore((s) => s.redo);

  const selectedRoi = rois.find((r) => r.id === selectedId) ?? null;

  // Ajusta el tamaño del canvas y lo vuelve a dibujar cuando cambian sus propiedades
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = width;
    canvas.height = height;
    redrawCanvas(canvas, rois, selectedId, cameraId, previewRef.current);
  }, [width, height, cameraId, rois, selectedId]);

  // Redibuja el canvas cuando cambian los ROIs o la selección
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    redrawCanvas(canvas, rois, selectedId, cameraId, previewRef.current);
  }, [rois, selectedId, cameraId]);

  useEffect(() => {
    console.table(
      rois.map((roi) => ({
        id: roi.id,
        cameraId: roi.cameraId,
        label: roi.label,
        x: roi.x,
        y: roi.y,
        width: roi.width,
        height: roi.height,
        isEnabled: roi.isEnabled,
      }))
    );
  }, [rois]);

  // Atajos de teclado para eliminar, deshacer y rehacer cambios
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const { selectedId: sid } = useROIStore.getState();
        if (sid) {
          e.preventDefault();
          deleteRoi(sid);
        }
      } else if (e.ctrlKey && e.shiftKey && (e.key === 'Z' || e.key === 'z')) {
        e.preventDefault();
        redo();
      } else if (e.ctrlKey && (e.key === 'z' || e.key === 'Z')) {
        e.preventDefault();
        undo();
      } else if (e.ctrlKey && (e.key === 'y' || e.key === 'Y')) {
        e.preventDefault();
        redo();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [deleteRoi, undo, redo]);

  function toNorm(e: React.MouseEvent<HTMLCanvasElement>): { nx: number; ny: number } {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      nx: (e.clientX - rect.left) / rect.width,
      ny: (e.clientY - rect.top) / rect.height,
    };
  }

  function onMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    if (e.button !== 0) return;
    const { nx, ny } = toNorm(e);
    const canvas = canvasRef.current!;
    const w = canvas.width;
    const h = canvas.height;

    const cameraRois = rois.filter((r) => r.cameraId === cameraId);

    // Primero comprueba si se hizo clic en un manejador del ROI seleccionado
    if (selectedId) {
      const selRoi = cameraRois.find((r) => r.id === selectedId);
      if (selRoi) {
        const handle = hitTestHandle(selRoi, nx, ny, w, h);
        if (handle !== null) {
          dragRef.current = {
            kind: 'resizing',
            roiId: selRoi.id,
            handle,
            origRoi: { ...selRoi },
          };
          return;
        }
      }
    }

    // Después comprueba si se hizo clic dentro de algún ROI visible
    for (let i = cameraRois.length - 1; i >= 0; i--) {
      const roi = cameraRois[i];
      if (hitTest(roi, nx, ny)) {
        selectRoi(roi.id);
        dragRef.current = {
          kind: 'moving',
          roiId: roi.id,
          startNx: nx,
          startNy: ny,
          origX: roi.x,
          origY: roi.y,
        };
        return;
      }
    }

    // Si no se encontró un ROI, comienza a dibujar uno nuevo
    selectRoi(null);
    dragRef.current = { kind: 'drawing', startNx: nx, startNy: ny };
    previewRef.current = { x: nx, y: ny, width: 0, height: 0 };
  }

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (drag.kind === 'none') return;

    const { nx, ny } = toNorm(e);
    const canvas = canvasRef.current!;

    if (drag.kind === 'drawing') {
      const x = Math.min(drag.startNx, nx);
      const y = Math.min(drag.startNy, ny);
      const w = Math.abs(nx - drag.startNx);
      const h = Math.abs(ny - drag.startNy);
      previewRef.current = { x, y, width: w, height: h };
      redrawCanvas(canvas, rois, selectedId, cameraId, previewRef.current);
      return;
    }

    if (drag.kind === 'moving') {
      const roi = rois.find((r) => r.id === drag.roiId);
      if (!roi) return;
      const dx = nx - drag.startNx;
      const dy = ny - drag.startNy;
      const newX = Math.max(0, Math.min(1 - roi.width, drag.origX + dx));
      const newY = Math.max(0, Math.min(1 - roi.height, drag.origY + dy));
      updateRoiDirect(drag.roiId, { x: newX, y: newY });
      return;
    }

    if (drag.kind === 'resizing') {
      const orig = drag.origRoi;
      let x = orig.x;
      let y = orig.y;
      let width: number;
      let height: number;
      const h = drag.handle;

      if (h === 0) {
        // Esquina superior izquierda
        const newX = Math.min(orig.x + orig.width - MIN_NORM, nx);
        const newY = Math.min(orig.y + orig.height - MIN_NORM, ny);
        width = orig.x + orig.width - newX;
        height = orig.y + orig.height - newY;
        x = newX;
        y = newY;
      } else if (h === 1) {
        // Esquina superior derecha
        const newY = Math.min(orig.y + orig.height - MIN_NORM, ny);
        width = Math.max(MIN_NORM, nx - orig.x);
        height = orig.y + orig.height - newY;
        y = newY;
      } else if (h === 2) {
        // Esquina inferior derecha
        width = Math.max(MIN_NORM, nx - orig.x);
        height = Math.max(MIN_NORM, ny - orig.y);
      } else {
        // Esquina inferior izquierda
        const newX = Math.min(orig.x + orig.width - MIN_NORM, nx);
        width = orig.x + orig.width - newX;
        height = Math.max(MIN_NORM, ny - orig.y);
        x = newX;
      }

      // Mantiene las coordenadas dentro de los límites del canvas
      x = Math.max(0, Math.min(1 - MIN_NORM, x));
      y = Math.max(0, Math.min(1 - MIN_NORM, y));
      width = Math.max(MIN_NORM, Math.min(1 - x, width));
      height = Math.max(MIN_NORM, Math.min(1 - y, height));

      updateRoiDirect(drag.roiId, { x, y, width, height });
    }
  }

  function onMouseUp(e: React.MouseEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    const canvas = canvasRef.current!;

    if (drag.kind === 'drawing') {
      const { nx, ny } = toNorm(e);
      const x = Math.min(drag.startNx, nx);
      const y = Math.min(drag.startNy, ny);
      const w = Math.abs(nx - drag.startNx);
      const h = Math.abs(ny - drag.startNy);

      previewRef.current = null;

      // Solo crea el ROI si supera el tamaño mínimo en ambas dimensiones
      if (w * canvas.width > MIN_PX && h * canvas.height > MIN_PX) {
        addRoi({ cameraId, label: 'ROI', x, y, width: w, height: h, isEnabled: true });
      } else {
        redrawCanvas(canvas, rois, selectedId, cameraId, null);
      }
    } else if (drag.kind === 'moving' || drag.kind === 'resizing') {
      pushHistory();
    }

    dragRef.current = { kind: 'none' };
  }

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          cursor: 'crosshair',
          pointerEvents: 'auto',
        }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
      />

      {/* T-22 + T-23: Editor de etiqueta sobre el canvas */}
      {selectedRoi && (
        <div
          style={{
            position: 'absolute',
            bottom: 8,
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: 'rgba(31, 36, 48, 0.92)',
            borderRadius: 8,
            padding: '6px 10px',
            pointerEvents: 'auto',
            zIndex: 10,
          }}
        >
          <input
            value={selectedRoi.label}
            onChange={(ev) => {
              const val = ev.target.value;
              // Actualiza la etiqueta mientras se escribe y la confirma al perder el foco
              useROIStore.getState().updateRoiDirect(selectedRoi.id, { label: val });
            }}
            onBlur={(ev) => {
              const trimmed = ev.target.value.trim();
              if (trimmed) setLabel(selectedRoi.id, trimmed);
            }}
            placeholder="Etiqueta"
            style={{
              height: 28,
              width: 120,
              padding: '0 8px',
              borderRadius: 6,
              border: '1px solid #3a4155',
              background: '#2a2f3e',
              color: '#e5e7eb',
              fontSize: 12,
              outline: 'none',
            }}
          />
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              color: '#9ca3af',
              fontSize: 12,
              cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            <input
              type="checkbox"
              checked={selectedRoi.isEnabled}
              onChange={(ev) => setEnabled(selectedRoi.id, ev.target.checked)}
              style={{ accentColor: selectedRoi.color }}
            />
            Activo
          </label>
          <button
            type="button"
            onClick={() => deleteRoi(selectedRoi.id)}
            style={{
              height: 28,
              padding: '0 8px',
              borderRadius: 6,
              border: 'none',
              background: '#d64545',
              color: '#fff',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Eliminar
          </button>
        </div>
      )}
    </div>
  );
}
