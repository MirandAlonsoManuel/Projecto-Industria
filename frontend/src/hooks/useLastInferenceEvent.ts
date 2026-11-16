import { useQuery } from '@tanstack/react-query';
import { loadLastInferenceEvent, type LastInferenceEvent } from '../services/lastInferenceEvent';
import { queryKeys } from '../services/queryClient';

/** Último evento de inferencia guardado en IndexedDB (null si aún no hay ninguno). */
export function useLastInferenceEvent(): LastInferenceEvent | null {
  const { data } = useQuery({
    queryKey: queryKeys.lastInferenceEvent,
    queryFn: loadLastInferenceEvent,
    // Lee del navegador, no del backend: debe funcionar aunque no haya conexión.
    networkMode: 'always',
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    // T-036: lectura local del navegador; si falla, simplemente no hay último evento
    meta: { notify: 'none' },
  });
  return data ?? null;
}
