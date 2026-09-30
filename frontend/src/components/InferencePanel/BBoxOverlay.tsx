import { useState } from 'react';
import type { BoundingBoxXYXY } from '../../types';

interface Box {
  bbox: BoundingBoxXYXY;
  label?: string;
  color?: string;
}

interface BBoxOverlayProps {
  imageUrl: string;
  boxes: Box[];
}

/** Dibuja bounding boxes (en espacio de imagen original) sobre la imagen que se les envió a inferir. */
export function BBoxOverlay({ imageUrl, boxes }: BBoxOverlayProps) {
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);

  return (
    <div className="relative w-full bg-[#1f2430] rounded-lg overflow-hidden">
      <img
        src={imageUrl}
        alt="Resultado de inferencia"
        className="w-full h-auto block"
        onLoad={(e) => {
          const img = e.currentTarget;
          setNatural({ width: img.naturalWidth, height: img.naturalHeight });
        }}
      />
      {natural &&
        boxes.map((box, i) => {
          const left = (box.bbox.x1 / natural.width) * 100;
          const top = (box.bbox.y1 / natural.height) * 100;
          const width = ((box.bbox.x2 - box.bbox.x1) / natural.width) * 100;
          const height = ((box.bbox.y2 - box.bbox.y1) / natural.height) * 100;
          const color = box.color ?? '#2f6fe4';
          return (
            <div
              key={i}
              className="absolute border-2 rounded"
              style={{
                left: `${left}%`,
                top: `${top}%`,
                width: `${width}%`,
                height: `${height}%`,
                borderColor: color,
              }}
            >
              {box.label && (
                <span
                  className="absolute -top-5 left-0 text-[11px] text-white px-1.5 py-px rounded whitespace-nowrap"
                  style={{ backgroundColor: color }}
                >
                  {box.label}
                </span>
              )}
            </div>
          );
        })}
    </div>
  );
}
