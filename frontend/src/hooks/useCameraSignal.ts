import { onlineManager, useQuery } from '@tanstack/react-query';
import { getSignal } from '../services/cameraApi';
import { queryKeys } from '../services/queryClient';

interface UseCameraSignalResult {
  hasSignal: boolean;
  isLoading: boolean;
  error: string | null;
}

// Polling de GET /signal — health check del servidor, sin parámetros de cámara.
// hasSignal === true significa que el backend está vivo y respondiendo.
//
// Además es quien le dice a React Query si hay conexión: el navegador solo sabe
// si hay red, no si el backend está caído. Al volver la señal, las consultas
// pausadas se reanudan y las cacheadas se refrescan solas.
async function checkSignal() {
  try {
    const signal = await getSignal();
    onlineManager.setOnline(true);
    return signal;
  } catch (error) {
    onlineManager.setOnline(false);
    throw error;
  }
}

export function useCameraSignal(intervalMs = 3000): UseCameraSignalResult {
  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.signal,
    queryFn: checkSignal,
    // T-036: corre cada 3 s; solo avisa si el servidor está caído (un único toast)
    meta: { notify: 'network-only' },
    refetchInterval: intervalMs,
    // 'always': debe seguir consultando aunque onlineManager marque offline,
    // si no nunca se detectaría la reconexión.
    networkMode: 'always',
    retry: false,
    staleTime: 0,
  });

  return {
    hasSignal: !isError && (data?.connected ?? false),
    isLoading: isPending,
    error: isError ? 'Servidor no disponible' : null,
  };
}
