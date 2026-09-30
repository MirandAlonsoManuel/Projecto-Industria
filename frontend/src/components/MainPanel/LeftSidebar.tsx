import type { Camera, Model, ROI } from '../../types/index';

interface LeftSidebarProps {
  camera: Camera;
  model: Model;
  rois: ROI[];
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 py-1.5 border-b border-[#f1f2f4] text-[13px]">
      <span className="text-[#6b7280]">{label}</span>
      <span className="font-semibold text-right">{value}</span>
    </div>
  );
}

export function LeftSideBar({ camera, model, rois }: LeftSidebarProps) {
  return (
    <aside className="flex flex-col gap-4 min-h-0">
      <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4">
        <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280] mb-[10px]">
          Cámara y modelo
        </p>
        <InfoRow label="Cámara" value={camera.name} />
        <InfoRow label="Protocolo" value={camera.protocol.toUpperCase()} />
        <InfoRow
          label="Resolución"
          value={`${camera.resolution.width}×${camera.resolution.height}`}
        />
        <InfoRow label="FPS" value={String(camera.fps)} />
        <InfoRow label="Modelo" value={model.name} />
        <InfoRow label="Sensibilidad" value={`${Math.round(model.confidenceThreshold * 100)}%`} />
      </section>

      <section className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4">
        <p className="text-xs font-semibold uppercase tracking-[0.04em] text-[#6b7280] mb-[10px]">
          Zonas de interés
        </p>
        {rois.map((roi) => (
          <div key={roi.id} className="w-2 h-2 rounded-full shrink-0">
            <span
              className={`"w-2 h-2 rounded-full shrink-0" ${roi.isEnabled ? 'w-2 h-2 rounded-full shrink-0 bg-[#2f6fe4]' : 'w-2 h-2 rounded-full shrink-0 bg-[#c7ccd3]'}`}
            />
            <span className="text-[#1f2430]">{roi.label}</span>
          </div>
        ))}
      </section>
    </aside>
  );
}
