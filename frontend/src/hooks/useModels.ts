import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getModels } from '../services/modelsApi';
import { queryKeys } from '../services/queryClient';
import type { ApiModel, ModelTask } from '../types';

interface UseModelsResult {
  models: ApiModel[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
  /** Modelos agrupados por tarea, útil para poblar el selector por pestaña de inferencia */
  byTask: Record<ModelTask, ApiModel[]>;
}

const EMPTY_MODELS: ApiModel[] = [];

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
  const {
    data,
    isLoading,
    isError,
    refetch: refetchQuery,
  } = useQuery({
    queryKey: queryKeys.models,
    queryFn: getModels,
    meta: { errorTitle: 'No se pudo cargar la lista de modelos' }, // T-036
  });

  const models = data ?? EMPTY_MODELS;
  // Si hay datos en caché se siguen mostrando aunque el último refresco haya fallado.
  const error = isError && !data ? 'No se pudo obtener el listado de modelos.' : null;

  const refetch = useCallback(() => {
    void refetchQuery();
  }, [refetchQuery]);

  // Memoizado para que los consumidores (p. ej. el efecto que preselecciona el
  // modelo por defecto en InferencePanel) puedan depender de esta referencia sin
  // volver a dispararse en cada render que no cambie la lista de modelos.
  const byTask = useMemo(() => (models.length ? groupByTask(models) : EMPTY_BY_TASK), [models]);

  return { models, isLoading, error, refetch, byTask };
}
