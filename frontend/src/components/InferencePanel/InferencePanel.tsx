import { useEffect, useState } from 'react';
import type { InferenceResult, ModelTask, ROIRect } from '../../types';
import { useModels } from '../../hooks/useModels';
import {
  parseInferenceError,
  runAnomaly,
  runClassification,
  runLocalization,
  runOcr,
} from '../../services/inferenceApi';
import { TaskTabs } from './TaskTabs';
import { ModelPicker } from './ModelPicker';
import { ImageDropzone } from './ImageDropzone';
import { ResultPanel } from './ResultPanel';
import { LiveInferenceViewer } from './LiveInferenceViewer';
import { ButtonCommon } from '../CommonComponents';

type RunStatus = 'idle' | 'running' | 'success' | 'error';

const ROI_FIELDS = ['x', 'y', 'width', 'height'] as const;

export function InferencePanel() {
  const { byTask, isLoading: isLoadingModels, error: modelsError } = useModels();
  const [task, setTask] = useState<ModelTask>('anomaly');
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [referenceImage, setReferenceImage] = useState<File | null>(null);
  const [roiEnabled, setRoiEnabled] = useState(false);
  const [roi, setRoi] = useState<ROIRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [status, setStatus] = useState<RunStatus>('idle');
  const [result, setResult] = useState<InferenceResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  const modelsForTask = byTask[task];

  // Al cambiar de tarea, preselecciona el modelo marcado como default y limpia el resultado anterior.
  useEffect(() => {
    const applyDefaults = () => {
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

  const handleTaskChange = (next: ModelTask) => {
    setTask(next);
    setImage(null);
    setReferenceImage(null);
  };

  const canRun =
    !!selectedModelId &&
    !!image &&
    (task !== 'anomaly' || !!referenceImage) &&
    status !== 'running';

  const handleRun = async () => {
    if (!selectedModelId || !image) return;
    setStatus('running');
    setErrorMessage(null);
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
    } catch (err) {
      setErrorMessage(parseInferenceError(err));
      setStatus('error');
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
            <ImageDropzone label="Imagen a analizar" file={image} onChange={setImage} />
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
            )}
          </section>

          <ButtonCommon variant="primary" disabled={!canRun} onClick={handleRun}>
            {status === 'running' ? 'Ejecutando…' : 'Ejecutar inferencia'}
          </ButtonCommon>

          {errorMessage && (
            <p className="text-[13px] font-semibold text-[#d64545]">{errorMessage}</p>
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
