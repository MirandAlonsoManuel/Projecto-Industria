import { useQuery } from '@tanstack/react-query';
import { getCameras, type ApiCamera } from '../services/cameraApi';
import { queryKeys } from '../services/queryClient';

interface UseCamerasResult {
  cameras: ApiCamera[];
  /** true cuando el backend respondió y reportó cero cámaras */
  noCamerasDetected: boolean;
  /** Aviso para el usuario (sin cámaras o listado no disponible), null si todo va bien */
  message: string | null;
}

const EMPTY_CAMERAS: ApiCamera[] = [];

export function useCameras(): UseCamerasResult {
  const { data, isError } = useQuery({
    queryKey: queryKeys.cameras,
    queryFn: getCameras,
    meta: { errorTitle: 'No se pudo cargar la lista de cámaras' }, // T-036
  });

  if (data) {
    const noCamerasDetected = data.total === 0;
    return {
      cameras: data.cameras,
      noCamerasDetected,
      message: noCamerasDetected ? (data.description ?? 'No se detectaron cámaras.') : null,
    };
  }

  return {
    cameras: EMPTY_CAMERAS,
    noCamerasDetected: isError,
    message: isError ? 'No se pudo consultar el listado de cámaras.' : null,
  };
}
