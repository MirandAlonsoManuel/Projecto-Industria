/**
 * T-27: LiveInferenceViewer — sliders for conf / iou / inferEveryNFrames.
 */
import { useState } from 'react';
import { useInferenceStream } from '../../hooks/useInferenceStream';
import { BBoxOverlay } from './BBoxOverlay';
import { ButtonCommon } from '../CommonComponents';

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}

function SliderField({ label, value, min, max, step, onChange }: SliderProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[12px] text-[#6b7280] w-32 shrink-0">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-[#2f6fe4]"
      />
      <span className="text-[12px] text-[#1f2430] w-8 text-right tabular-nums">{value}</span>
    </div>
  );
}

/** Stream en vivo de /ws/inference-stream: video + detecciones YOLO incrustadas por frame. */
export function LiveInferenceViewer() {
  const [cameraId, setCameraId] = useState('0');
  const [isActive, setIsActive] = useState(false);
  const [conf, setConf] = useState(0.25);
  const [iou, setIou] = useState(0.45);
  const [inferEveryNFrames, setInferEveryNFrames] = useState(3);

  return (
    <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280]">
          Stream en vivo con detecciones
        </p>
        <div className="flex items-center gap-2">
          <input
            value={cameraId}
            onChange={(e) => setCameraId(e.target.value)}
            disabled={isActive}
            className="h-8 w-20 px-2 rounded-lg border border-[#e2e5ea] text-[13px]"
            aria-label="ID de cámara"
          />
          <ButtonCommon variant="secondary" onClick={() => setIsActive((v) => !v)}>
            {isActive ? 'Detener' : 'Conectar'}
          </ButtonCommon>
        </div>
      </div>

      {/* T-27: Sliders */}
      <div className="flex flex-col gap-1.5">
        <SliderField
          label="Confianza mín."
          value={conf}
          min={0.05}
          max={0.95}
          step={0.05}
          onChange={setConf}
        />
        <SliderField label="IoU" value={iou} min={0.05} max={0.95} step={0.05} onChange={setIou} />
        <SliderField
          label="Inferir cada N frames"
          value={inferEveryNFrames}
          min={1}
          max={10}
          step={1}
          onChange={setInferEveryNFrames}
        />
      </div>

      {isActive && (
        <LiveInferenceStream
          cameraId={cameraId}
          conf={conf}
          iou={iou}
          inferEveryNFrames={inferEveryNFrames}
        />
      )}
    </section>
  );
}

interface LiveInferenceStreamProps {
  cameraId: string;
  conf: number;
  iou: number;
  inferEveryNFrames: number;
}

function LiveInferenceStream({ cameraId, conf, iou, inferEveryNFrames }: LiveInferenceStreamProps) {
  const { frameUrl, detections, isConnected, error } = useInferenceStream(cameraId, {
    conf,
    iou,
    inferEveryNFrames,
  });

  if (error) {
    return <p className="text-[13px] font-semibold text-[#d64545]">{error}</p>;
  }

  if (!isConnected || !frameUrl) {
    return <p className="text-[13px] text-[#6b7280]">Conectando…</p>;
  }

  return (
    <BBoxOverlay
      imageUrl={frameUrl}
      boxes={detections.map((d) => ({
        bbox: d.bbox,
        label: `${d.className ?? `clase ${d.classId}`} ${Math.round(d.confidence * 100)}%`,
      }))}
    />
  );
}
