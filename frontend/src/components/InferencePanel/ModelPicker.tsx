import type { ApiModel } from '../../types';

interface ModelPickerProps {
  models: ApiModel[];
  selectedModelId: string | null;
  onChange: (modelId: string) => void;
  isLoading: boolean;
}

function unavailableReason(model: ApiModel): string {
  if (!model.enabled) return 'Deshabilitado en el registry';
  if (!model.available) return `Falta instalar el backend "${model.backend}"`;
  return '';
}

export function ModelPicker({ models, selectedModelId, onChange, isLoading }: ModelPickerProps) {
  if (isLoading) {
    return <p className="text-[13px] text-[#6b7280]">Cargando modelos…</p>;
  }

  if (models.length === 0) {
    return (
      <p className="text-[13px] text-[#6b7280]">No hay modelos registrados para esta tarea.</p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {models.map((model) => {
        const isSelected = model.id === selectedModelId;
        const disabled = !model.available || !model.enabled;
        const reason = unavailableReason(model);

        return (
          <label
            key={model.id}
            className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-[13px] ${
              disabled ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'
            } ${isSelected ? 'border-[#2f6fe4] bg-[rgba(47,111,228,0.06)]' : 'border-[#e2e5ea] bg-white'}`}
          >
            <span className="flex items-center gap-2">
              <input
                type="radio"
                name="model-picker"
                checked={isSelected}
                disabled={disabled}
                onChange={() => onChange(model.id)}
              />
              <span className="flex flex-col">
                <span className="font-semibold text-[#1f2430]">
                  {model.id}
                  {model.default && (
                    <span className="ml-1.5 text-[11px] font-normal text-[#6b7280]">(default)</span>
                  )}
                </span>
                {reason && <span className="text-[11px] text-[#d64545]">{reason}</span>}
              </span>
            </span>
            <span
              className={`shrink-0 text-[11px] font-bold py-0.5 px-2 rounded-full ${
                model.available
                  ? 'bg-[rgba(30,158,99,0.12)] text-[#1e9e63]'
                  : 'bg-[rgba(214,69,69,0.12)] text-[#d64545]'
              }`}
            >
              {model.available ? 'Disponible' : 'No disponible'}
            </span>
          </label>
        );
      })}
    </div>
  );
}
