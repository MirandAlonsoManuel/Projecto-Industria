import type { InferenceResult } from '../../types';
import { BBoxOverlay } from './BBoxOverlay';

interface ResultPanelProps {
  result: InferenceResult;
  imageUrl: string;
}

function Bar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-[12px] text-[#1f2430]">
        <span className="font-semibold">{label}</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 rounded-full bg-[#f1f2f4] overflow-hidden">
        <div className="h-full bg-[#2f6fe4] rounded-full" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function ResultPanel({ result, imageUrl }: ResultPanelProps) {
  if (result.task === 'localization') {
    return (
      <div className="flex flex-col gap-3">
        <BBoxOverlay
          imageUrl={imageUrl}
          boxes={result.detections.map((d) => ({
            bbox: d.bbox,
            label: `${d.className ?? `clase ${d.classId}`} ${Math.round(d.confidence * 100)}%`,
          }))}
        />
        {result.detections.length === 0 && (
          <p className="text-[13px] text-[#6b7280]">No se detectaron objetos.</p>
        )}
      </div>
    );
  }

  if (result.task === 'classification') {
    return (
      <div className="flex flex-col gap-3">
        {result.predictions.length === 0 && (
          <p className="text-[13px] text-[#6b7280]">Sin predicciones.</p>
        )}
        {result.predictions.map((p, i) => (
          <Bar key={i} label={p.label ?? `Clase ${p.classId}`} value={p.confidence} />
        ))}
      </div>
    );
  }

  if (result.task === 'ocr') {
    return (
      <div className="flex flex-col gap-2">
        {result.results.length === 0 && (
          <p className="text-[13px] text-[#6b7280]">No se reconoció texto en la imagen.</p>
        )}
        {result.results.map((r, i) => (
          <div
            key={i}
            className="flex justify-between gap-2 border-b border-[#f1f2f4] py-1.5 text-[13px]"
          >
            <span className="font-medium text-[#1f2430]">{r.text}</span>
            <span className="text-[#6b7280]">{Math.round(r.confidence * 100)}%</span>
          </div>
        ))}
      </div>
    );
  }

  // anomaly
  const isAnomalous = result.anomalyScore > 0;
  return (
    <div className="flex flex-col gap-3">
      <BBoxOverlay
        imageUrl={imageUrl}
        boxes={result.regions.map((r) => ({
          bbox: r.bbox,
          label: `${Math.round(r.score * 100)}%`,
          color: '#d64545',
        }))}
      />
      <div
        className={`rounded-lg px-3 py-2 text-[13px] font-semibold ${
          isAnomalous
            ? 'bg-[rgba(214,69,69,0.12)] text-[#d64545]'
            : 'bg-[rgba(30,158,99,0.12)] text-[#1e9e63]'
        }`}
      >
        Anomaly score: {result.anomalyScore.toFixed(3)} — {result.regions.length} región(es)
        detectada(s)
      </div>
    </div>
  );
}
