import { useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import type { InferenceResult, ModelTask, ROIRect } from '../../types';
import { useModels } from '../../hooks/useModels';
import { useLastInferenceEvent } from '../../hooks/useLastInferenceEvent';
import { recordInferenceEvent } from '../../services/lastInferenceEvent';
import {
  clearManualInferenceError,
  notifyManualInferenceError,
} from '../../services/errorNotifier';
import {
  parseInferenceError,
  runAnomaly,
  runClassification,
  runLocalization,
  runOcr,
} from '../../services/inferenceApi';
import { toNormalized, toPixels, isValidNormalizedRect } from '../../utils/roiCoords';
import { TaskTabs } from './TaskTabs';
import { ModelPicker } from './ModelPicker';
import { ImageDropzone } from './ImageDropzone';
import { ResultPanel } from './ResultPanel';
import { LiveInferenceViewer } from './LiveInferenceViewer';
import { ButtonCommon } from '../CommonComponents';

type RunStatus = 'idle' | 'running' | 'success' | 'error';

interface NormRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const ROI_FIELDS = ['x', 'y', 'width', 'height'] as const;

const TASK_LABELS: Record<ModelTask, string> = {
  localization: 'Localización',
  classification: 'Clasificación',
  ocr: 'OCR',
  anomaly: 'Anomalías',
};

function blobToFile(blob: Blob, name: string): File {
  return blob instanceof File ? blob : new File([blob], name, { type: blob.type });
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function InferencePanel() {
  const { byTask, isLoading: isLoadingModels, error: modelsError } = useModels();
  const [task, setTask] = useState<ModelTask>('anomaly');
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [referenceImage, setReferenceImage] = useState<File | null>(null);
  const [roiEnabled, setRoiEnabled] = useState(false);
  const [roi, setRoi] = useState<ROIRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [roiNatural, setRoiNatural] = useState<{ width: number; height: number } | null>(null);
  const [roiDragRect, setRoiDragRect] = useState<NormRect | null>(null);
  const roiDragStartRef = useRef<{ x: number; y: number } | null>(null);
  const [status, setStatus] = useState<RunStatus>('idle');
  const [result, setResult] = useState<InferenceResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  const lastEvent = useLastInferenceEvent();
  // true mientras lo que hay en pantalla viene del último evento recuperado: evita que
  // los efectos de "cambió la tarea/imagen" borren el modelo, ROI y resultado restaurados.
  const isRestoredRef = useRef(false);

  const modelsForTask = byTask[task];

  // Al cambiar de tarea, preselecciona el modelo marcado como default y limpia el resultado anterior.
  useEffect(() => {
    const applyDefaults = () => {
      if (isRestoredRef.current) return;
      const defaultModel = modelsForTask.find((m) => m.default) ?? modelsForTask[0];
      setSelectedModelId(defaultModel?.id ?? null);
      setStatus('idle');
      setResult(null);
      setErrorMessage(null);
    };
    applyDefaults();
  }, [task, modelsForTask]);

  useEffect(() => {
    const apply = () => {
      if (!image) {
        setImageUrl(null);
        return undefined;
      }
      const url = URL.createObjectURL(image);
      setImageUrl(url);
      return url;
    };
    const url = apply();
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [image]);

  // Reinicia el ROI dibujado al cambiar de imagen: las coordenadas en píxeles
  // ya no corresponden a las dimensiones naturales de la nueva imagen.
  useEffect(() => {
    if (isRestoredRef.current) return;
    const resetRoi = () => {
      setRoiNatural(null);
      setRoi({ x: 0, y: 0, width: 0, height: 0 });
    };
    resetRoi();
  }, [image]);

  const handleTaskChange = (next: ModelTask) => {
    isRestoredRef.current = false;
    setTask(next);
    setImage(null);
    setReferenceImage(null);
  };

  const handleImageChange = (file: File | null) => {
    isRestoredRef.current = false;
    setImage(file);
  };

  // Recarga en el panel el último evento guardado en IndexedDB (imagen o frame en vivo),
  // listo para revisarlo o volver a ejecutarlo con otro modelo/ROI.
  const handleRestoreLastEvent = () => {
    if (!lastEvent) return;
    const candidates = byTask[lastEvent.task];
    const model =
      candidates.find((m) => m.id === lastEvent.modelId) ??
      candidates.find((m) => m.default) ??
      candidates[0];

    isRestoredRef.current = true;
    setTask(lastEvent.task);
    setSelectedModelId(model?.id ?? null);
    setImage(blobToFile(lastEvent.image, lastEvent.imageName));
    setReferenceImage(
      lastEvent.referenceImage
        ? blobToFile(lastEvent.referenceImage, lastEvent.referenceImageName ?? 'referencia')
        : null
    );
    setRoiEnabled(!!lastEvent.roi);
    setRoi(lastEvent.roi ?? { x: 0, y: 0, width: 0, height: 0 });
    setResult(lastEvent.result);
    setStatus('success');
    setErrorMessage(null);
  };

  const getNormPointFromEvent = (e: ReactPointerEvent<HTMLDivElement>): { x: number; y: number } => {
    const rect = e.currentTarget.getBoundingClientRect();
    return {
      x: clamp01((e.clientX - rect.left) / rect.width),
      y: clamp01((e.clientY - rect.top) / rect.height),
    };
  };

  const handleRoiPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!roiNatural) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const point = getNormPointFromEvent(e);
    roiDragStartRef.current = point;
    setRoiDragRect({ x: point.x, y: point.y, width: 0, height: 0 });
  };

  const handleRoiPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const start = roiDragStartRef.current;
    if (!start) return;
    const point = getNormPointFromEvent(e);
    setRoiDragRect({
      x: Math.min(start.x, point.x),
      y: Math.min(start.y, point.y),
      width: Math.abs(point.x - start.x),
      height: Math.abs(point.y - start.y),
    });
  };

  const handleRoiPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    roiDragStartRef.current = null;
    const finalRect = roiDragRect;
    setRoiDragRect(null);
    if (finalRect && roiNatural && isValidNormalizedRect(finalRect)) {
      const pixelRect = toPixels(finalRect, roiNatural.width, roiNatural.height);
      setRoi({
        x: Math.round(pixelRect.x),
        y: Math.round(pixelRect.y),
        width: Math.round(pixelRect.width),
        height: Math.round(pixelRect.height),
      });
    }
  };

  // Rectángulo normalizado a mostrar: el que se está arrastrando, o el ya aplicado en `roi`.
  const roiOverlayRect =
    roiDragRect ??
    (roiNatural && roi.width > 0 && roi.height > 0
      ? toNormalized(roi, roiNatural.width, roiNatural.height)
      : null);

  const canRun =
    !!selectedModelId &&
    !!image &&
    (task !== 'anomaly' || !!referenceImage) &&
    status !== 'running';

  const handleRun = async () => {
    if (!selectedModelId || !image) return;
    setStatus('running');
    setErrorMessage(null);
    clearManualInferenceError(); // T-036: un intento nuevo quita el aviso anterior
    const roiParam = roiEnabled ? roi : undefined;

    try {
      let next: InferenceResult;
      switch (task) {
        case 'localization':
          next = await runLocalization(image, selectedModelId, roiParam);
          break;
        case 'classification':
          next = await runClassification(image, selectedModelId, 5, roiParam);
          break;
        case 'ocr':
          next = await runOcr(image, selectedModelId, roiParam);
          break;
        case 'anomaly':
          next = await runAnomaly(image, referenceImage as File, selectedModelId, roiParam);
          break;
      }
      setResult(next);
      setStatus('success');
      void recordInferenceEvent({
        source: 'image',
        task,
        modelId: selectedModelId,
        image,
        imageName: image.name,
        referenceImage: task === 'anomaly' ? (referenceImage ?? undefined) : undefined,
        referenceImageName: task === 'anomaly' ? referenceImage?.name : undefined,
        roi: roiParam ?? null,
        result: next,
      });
    } catch (err) {
      const message = parseInferenceError(err);
      // El texto junto al botón se queda; el toast agrega "Reintentar" (T-036)
      setErrorMessage(message);
      setStatus('error');
      notifyManualInferenceError(message, () => void handleRun());
    }
  };

  return (
    <div className="font-inter flex flex-col h-full w-full bg-[#f5f6f8] text-[#1f2430] p-4 gap-4 overflow-y-auto">
      <TaskTabs activeTask={task} onChange={handleTaskChange} />

      <div className="grid grid-cols-[300px_1fr] gap-4 min-h-0">
        <aside className="flex flex-col gap-4">
          <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4">
            <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280] mb-2.5">
              Modelo
            </p>
            {modelsError ? (
              <p className="text-[13px] text-[#d64545]">{modelsError}</p>
            ) : (
              <ModelPicker
                models={modelsForTask}
                selectedModelId={selectedModelId}
                onChange={setSelectedModelId}
                isLoading={isLoadingModels}
              />
            )}
          </section>

          <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex flex-col gap-3">
            <ImageDropzone label="Imagen a analizar" file={image} onChange={handleImageChange} />
            {task === 'anomaly' && (
              <ImageDropzone
                label="Imagen de referencia"
                file={referenceImage}
                onChange={setReferenceImage}
              />
            )}
          </section>

          <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex flex-col gap-2">
            <label className="flex items-center gap-2 text-[13px] font-semibold text-[#1f2430]">
              <input
                type="checkbox"
                checked={roiEnabled}
                onChange={(e) => setRoiEnabled(e.target.checked)}
              />
              Limitar a una zona (ROI)
            </label>
            {roiEnabled && (
              <>
                {imageUrl ? (
                  <div
                    onPointerDown={handleRoiPointerDown}
                    onPointerMove={handleRoiPointerMove}
                    onPointerUp={handleRoiPointerUp}
                    className="relative w-full rounded-lg overflow-hidden border border-[#e2e5ea] bg-[#1f2430] cursor-crosshair touch-none"
                  >
                    <img
                      src={imageUrl}
                      alt="Vista previa para dibujar el ROI"
                      className="w-full h-auto block select-none pointer-events-none"
                      draggable={false}
                      onLoad={(e) => {
                        const img = e.currentTarget;
                        setRoiNatural({ width: img.naturalWidth, height: img.naturalHeight });
                      }}
                    />
                    {roiOverlayRect && (
                      <div
                        className="absolute border-2 border-[#2f6fe4] bg-[rgba(47,111,228,0.15)] pointer-events-none"
                        style={{
                          left: `${roiOverlayRect.x * 100}%`,
                          top: `${roiOverlayRect.y * 100}%`,
                          width: `${roiOverlayRect.width * 100}%`,
                          height: `${roiOverlayRect.height * 100}%`,
                        }}
                      />
                    )}
                  </div>
                ) : (
                  <p className="text-[11px] text-[#6b7280]">
                    Sube una imagen para dibujar la zona directamente sobre ella.
                  </p>
                )}
                <p className="text-[11px] text-[#6b7280]">
                  Arrastra sobre la imagen para definir el ROI, o ajusta los valores manualmente.
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {ROI_FIELDS.map((field) => (
                    <label key={field} className="flex flex-col gap-1 text-[11px] text-[#6b7280]">
                      {field}
                      <input
                        type="number"
                        value={roi[field]}
                        onChange={(e) =>
                          setRoi((prev) => ({ ...prev, [field]: Number(e.target.value) }))
                        }
                        className="h-8 px-2 rounded-lg border border-[#e2e5ea] text-[13px]"
                      />
                    </label>
                  ))}
                </div>
              </>
            )}
          </section>

          <ButtonCommon variant="primary" disabled={!canRun} onClick={handleRun}>
            {status === 'running' ? 'Ejecutando…' : 'Ejecutar inferencia'}
          </ButtonCommon>

          {errorMessage && (
            <p className="text-[13px] font-semibold text-[#d64545]">{errorMessage}</p>
          )}

          {lastEvent && (
            <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex flex-col gap-2">
              <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280]">
                Último evento
              </p>
              <p className="text-[12px] text-[#1f2430]">
                {TASK_LABELS[lastEvent.task]} ·{' '}
                {lastEvent.source === 'live'
                  ? `en vivo, cámara ${lastEvent.cameraId ?? '?'}`
                  : lastEvent.imageName}
              </p>
              <p className="text-[11px] text-[#6b7280]">
                {new Date(lastEvent.createdAt).toLocaleString()}
                {lastEvent.roi ? ' · con ROI' : ''}
              </p>
              <ButtonCommon variant="secondary" onClick={handleRestoreLastEvent}>
                Recuperar
              </ButtonCommon>
            </section>
          )}
        </aside>

        <main className="flex flex-col gap-4 min-h-0">
          <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex-1 min-h-0 overflow-y-auto">
            <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280] mb-2.5">
              Resultado
            </p>
            {result && imageUrl ? (
              <ResultPanel result={result} imageUrl={imageUrl} />
            ) : (
              <p className="text-[13px] text-[#6b7280]">
                Selecciona un modelo, sube una imagen y ejecuta la inferencia.
              </p>
            )}
          </section>

          {task === 'localization' && <LiveInferenceViewer />}
        </main>
      </div>
    </div>
  );
}

export default InferencePanel;
