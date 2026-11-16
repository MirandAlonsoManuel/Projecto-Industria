import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export interface AccuracyLevel {
  label: string;
  color: string;
  threshold: number;
  operator: '>=' | '<=';
}

const DEFAULT_LEVELS: AccuracyLevel[] = [
  { label: 'Alta',  color: '#B4D678', threshold: 70, operator: '>=' },
  { label: 'Media', color: '#A3C2DF', threshold: 50, operator: '>=' },
  { label: 'Baja',  color: '#BD7066', threshold: 30, operator: '<=' },
];

interface DetectionColorState {
  levels: AccuracyLevel[];
  updateLevel: (index: number, patch: Partial<AccuracyLevel>) => void;
}

export const useDetectionColorStore = create<DetectionColorState>()(
  persist(
    (set) => ({
      levels: DEFAULT_LEVELS,
      updateLevel: (index, patch) =>
        set((state) => ({
          levels: state.levels.map((l, i) => (i === index ? { ...l, ...patch } : l)),
        })),
    }),
    {
      name: 'detection-color-store',
      storage: createJSONStorage(() => localStorage),
    }
  )
);

/** Devuelve el color que corresponde a un confidence score (0-1) según los niveles configurados */
export function colorForConfidence(
  confidence: number,
  levels: AccuracyLevel[]
): string {
  const score = confidence * 100;
  for (const level of levels) {
    if (level.operator === '>=' && score >= level.threshold) return level.color;
    if (level.operator === '<=' && score <= level.threshold) return level.color;
  }
  return '#6b7280'; // fallback
}