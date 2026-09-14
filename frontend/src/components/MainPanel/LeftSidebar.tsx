import { useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Image,
  Camera,
  Cpu,
  ScanSearch,
  BarChart2,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  ChevronsLeft,
} from 'lucide-react';
import { ROICoordinatesPanel } from './ROICoordinatesPanel';

interface NavItem {
  label: string;
  icon: LucideIcon;
  children: string[];
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Imagen', icon: Image, children: ['ROI', 'Calibración'] },
  { label: 'Comunicación cámara', icon: Camera, children: ['Diagnóstico', 'Trigger'] },
  { label: 'Entrenamiento', icon: Cpu, children: ['Detección', 'Clasificación', 'Segmentación', 'OCR'] },
  { label: 'Inspección', icon: ScanSearch, children: ['Medición', 'non'] },
  { label: 'Resultados', icon: BarChart2, children: [] },
  { label: 'Ayuda', icon: HelpCircle, children: ['Manual de usuario', 'Contacto'] },
];

interface LeftSidebarProps {
  collapsed?: boolean;
  onCollapse?: () => void;
  cameraId: string;
  naturalWidth?: number;
  naturalHeight?: number;
}

export function LeftSideBar({
  collapsed = false,
  onCollapse,
  cameraId,
  naturalWidth,
  naturalHeight,
}: LeftSidebarProps) {
  const [openSections, setOpenSections] = useState<string[]>(['Imagen']);
  const [activeItem, setActiveItem] = useState<string | null>(null);

  const toggle = (label: string) => {
    setOpenSections((prev) =>
      prev.includes(label) ? prev.filter((s) => s !== label) : [...prev, label]
    );
  };

  return (
    <aside className="flex flex-col bg-white rounded-2xl border-[#e2e5ea] w-52 shrink-0 overflow-y-auto max-h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3.5 border-b border-[#e2e5ea]">
        {!collapsed && (
          <span className="text-[15px] font-semibold text-[#393939]">Herramientas</span>
        )}
        <button
          type="button"
          onClick={onCollapse}
          className="text-[#6b7280] hover:text-[#393939] transition-colors cursor-pointer ml-auto"
        >
          <ChevronsLeft size={18} />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex flex-col py-2 overflow-y-auto flex-1">
        {NAV_ITEMS.map(({ label, icon: Icon, children }) => {
          const isOpen = openSections.includes(label);
          const hasChildren = children.length > 0;

          return (
            <div key={label}>
              {/* Section header */}
              <button
                type="button"
                onClick={() => hasChildren && toggle(label)}
                className="w-full flex items-center gap-2.5 px-4 py-2 text-[13px] font-semibold text-[#1f2430] hover:bg-[#f5f6f8] transition-colors cursor-pointer"
              >
                {hasChildren ? (
                  isOpen ? <ChevronDown size={14} className="text-[#6b7280] shrink-0" />
                           : <ChevronRight size={14} className="text-[#6b7280] shrink-0" />
                ) : (
                  <span className="w-3.5 shrink-0" />
                )}
                <Icon size={15} className="shrink-0 text-[#6b7280]" />
                {label}
              </button>

              {/* Children */}
              {hasChildren && isOpen && (
                <div className="flex flex-col">
                  {children.map((child) => {
                    const isActive = activeItem === child;
                    return (
                      <button
                        key={child}
                        type="button"
                        onClick={() => setActiveItem(child)}
                        className={`w-full text-left pl-20 pr-4 py-1.5 text-[13px] border-l-2 transition-colors cursor-pointer ${
                          isActive
                            ? 'border-[#2f6fe4] text-[#2f6fe4] font-semibold bg-[rgba(47,111,228,0.06)]'
                            : 'border-transparent text-[#6b7280] hover:text-[#1f2430] hover:bg-[#f5f6f8]'
                        }`}
                      >
                        {child}
                      </button>
                    );
                  })}

                  {label === 'Imagen' && activeItem === 'ROI' && (
                    <div className="px-3 pb-2">
                      <ROICoordinatesPanel
                        cameraId={cameraId}
                        naturalWidth={naturalWidth}
                        naturalHeight={naturalHeight}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}