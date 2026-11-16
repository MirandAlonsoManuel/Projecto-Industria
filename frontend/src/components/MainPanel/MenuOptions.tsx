import { useState } from 'react';
import { AccuracyColorPanel } from './AccuracyColorPanel';
import { ROICoordinatesPanel } from './ROICoordinatesPanel';

interface MenuOptionsProps {
  cameraId: string;
  naturalWidth?: number;
  naturalHeight?: number;
  menuOptionSelected: string;
}

// Componente reutilizable de tabs
function TabBar({
  tabs,
  active,
  onChange,
}: {
  tabs: string[];
  active: string;
  onChange: (tab: string) => void;
}) {
  return (
    <div className="flex gap-1 rounded-3xl p-1 w-fit ">
      {tabs.map((tab) => (
        <button
          key={tab}
          type="button"
          onClick={() => onChange(tab)}
          className={`px-4 py-0.5 rounded-3xl text-[13px] transition-colors cursor-pointer ${
            active === tab
              ? 'bg-[#393939] text-white shadow-sm'
              : 'text-[#393939] hover:text-[#393939]'
          }`}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

const ROI_TABS = ['Imagen de referencia', 'Zonas de interés ROI'];
function ROIMenu({ cameraId, naturalWidth, naturalHeight }: {
  cameraId: string;
  naturalWidth?: number;
  naturalHeight?: number;
}) {
  const [tab, setTab] = useState(ROI_TABS[0]);
  return (
    <div className="flex flex-col gap-3 w-5/6">
      <TabBar tabs={ROI_TABS} active={tab} onChange={setTab} />
      {tab === 'Imagen de referencia' && (
        <div className="text-[13px] text-[#6b7280]">Aqui va ir donde se va a subir la imagen de referencia</div>
      )}
      {tab === 'Zonas de interés ROI' && (
        <ROICoordinatesPanel
          cameraId={cameraId}
          naturalWidth={naturalWidth}
          naturalHeight={naturalHeight}
        />
      )}
    </div>
  );
}

const CLASIFICACION_TABS = ['Detección', 'Accuracy'];
function ClasificacionMenu() {
  const [tab, setTab] = useState(CLASIFICACION_TABS[0]);
  return (
    <div className="flex flex-col gap-3 w-5/6">
      <TabBar tabs={CLASIFICACION_TABS} active={tab} onChange={setTab} />
      {tab === 'Detección' && (
        <div className="text-[13px] text-[#6b7280]">Aquí va el panel de las detecciones</div>
      )}
      {tab === 'Accuracy' && <AccuracyColorPanel />}
    </div>
  );
}

const LOCALIZACION_TABS = ['Imagen de referencia'];
function LocalizacionMenu() {
  const [tab, setTab] = useState(LOCALIZACION_TABS[0]);
  return (
    <div className="flex flex-col gap-3 w-5/6">
      <TabBar tabs={LOCALIZACION_TABS} active={tab} onChange={setTab} />
      {tab === 'Imagen de referencia' && (
        <div className="text-[13px] text-[#6b7280]">Aqui va ir donde se va a subir la imagen de referencia</div>
      )}
    </div>
  );
}

const OCR_TABS = ['Imagen de referencia'];
function OCRMenu() {
  const [tab, setTab] = useState(OCR_TABS[0]);
  return (
    <div className="flex flex-col gap-3 w-5/6">
      <TabBar tabs={OCR_TABS} active={tab} onChange={setTab} />
      {tab === 'Imagen de referencia' && (
        <div className="text-[13px] text-[#6b7280]">Aqui va ir donde se va a subir la imagen de referencia</div>
      )}
    </div>
  );
}

export function MenuOptions({ cameraId, naturalWidth, naturalHeight, menuOptionSelected }: MenuOptionsProps) {
  switch (menuOptionSelected) {
    case 'ROI':
      return (
      <div className="flex flex-col gap-3 w-5/6">
        <ROICoordinatesPanel cameraId={cameraId} naturalWidth={naturalWidth} naturalHeight={naturalHeight}/>
      </div>
      )
    case 'Detección':
      return <ROIMenu cameraId={cameraId} naturalWidth={naturalWidth} naturalHeight={naturalHeight} />;
    case 'Clasificación':
      return <ClasificacionMenu />;
    case 'Segmentación':
      return <LocalizacionMenu />;
    case 'OCR':
      return <OCRMenu />;
    default:
      return null;
  }
}