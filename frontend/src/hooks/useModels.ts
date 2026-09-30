import { useCallback, useEffect, useMemo, useState } from 'react';
import { getModels } from '../services/modelsApi';
import type { ApiModel, ModelTask } from '../types';

interface UseModelsResult {
  models: ApiModel[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
  /** Modelos agrupados por tarea, útil para poblar el selector por pestaña de inferencia */
  byTask: Record<ModelTask, ApiModel[]>;
}

const EMPTY_BY_TASK: Record<ModelTask, ApiModel[]> = {
  localization: [],
  classification: [],
  ocr: [],
  anomaly: [],
};

function groupByTask(models: ApiModel[]): Record<ModelTask, ApiModel[]> {
  const grouped: Record<ModelTask, ApiModel[]> = {
    localization: [],
    classification: [],
    ocr: [],
    anomaly: [],
  };
  for (const model of models) {
    grouped[model.task]?.push(model);
  }
  return grouped;
}

export function useModels(): UseModelsResult {
  const [models, setModels] = useState<ApiModel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setIsLoading(true);
      try {
        const data = await getModels();
        if (cancelled) return;
        setModels(data);
        setError(null);
      } catch {
        if (!cancelled) setError('No se pudo obtener el listado de modelos.');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    load();

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const refetch = useCallback(() => setReloadToken((t) => t + 1), []);

  // Memoizado para que los consumidores (p. ej. el efecto que preselecciona el
  // modelo por defecto en InferencePanel) puedan depender de esta referencia sin
  // volver a dispararse en cada render que no cambie la lista de modelos.
  const byTask = useMemo(() => (models.length ? groupByTask(models) : EMPTY_BY_TASK), [models]);

  return { models, isLoading, error, refetch, byTask };
}
