import { useState, useEffect } from 'react';
import { getSignal } from '../services/cameraApi';

interface UseCameraSignalResult {
  hasSignal: boolean;
  isLoading: boolean;
  error: string | null;
}

// Polling de GET /signal — health check del servidor, sin parámetros de cámara.
// hasSignal === true significa que el backend está vivo y respondiendo.
export function useCameraSignal(intervalMs = 3000): UseCameraSignalResult {
  const [hasSignal, setHasSignal] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const { connected } = await getSignal();
        if (!cancelled) {
          setHasSignal(connected);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setHasSignal(false);
          setError('Servidor no disponible');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    check();
    const interval = setInterval(check, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [intervalMs]);

  return { hasSignal, isLoading, error };
}
