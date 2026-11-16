import { useState } from 'react';
import { X, Check } from 'lucide-react';
import { CheckIcon, DeleteX, DeleteXMenu } from '../CommonComponents/Icons/IconCommon';
import { ButtonCommon } from '../CommonComponents';

const PALETTE = [
  '#A1725E', '#BD7066', '#E14930', '#E36044', '#E17C41', '#F1AE5E',
  '#71CE97', '#51A267', '#8FBC60', '#B4D678', '#F5E493', '#EDCD76',
  '#A3D9C1', '#A7D9E3', '#A3C2DF', '#557EDC', '#9996F4', '#B199F0',
  '#606261', '#C5B9BB', '#BDA4A7', '#E292AF', '#BB76DA', '#9B77D4',
];

interface ColorPickerPopupProps {
  currentColor: string;
  onSave: (color: string) => void;
  onClose: () => void;
}

export function ColorPickerPopup({ currentColor, onSave, onClose }: ColorPickerPopupProps) {
  const [selected, setSelected] = useState(currentColor);

  return (
    <div className="relative z-50 bg-white dark:bg-[#393939] dark:text-white rounded-3xl shadow-xl p-4 w-56">
      <button
        type="button"
        onClick={onClose}
        className="absolute right-3 text-[#474747] dark:text-[#f7f7f7] dark:hover:text-[#BFBFBF] hover:text-[#1f2430] cursor-pointer"
      >
        <DeleteXMenu></DeleteXMenu>
      </button>

      <div className="grid grid-cols-6 gap-2 mt-7">
        {PALETTE.map((color) => (
          <button
            key={color}
            type="button"
            onClick={() => setSelected(color)}
            className="w-6 h-6 rounded-md flex items-center justify-center cursor-pointer transition-transform hover:scale-110"
            style={{ backgroundColor: color }}
          >
            {selected === color && <Check size={14} color="#fff" strokeWidth={3} />}
          </button>
        ))}
      </div>

      <div className='flex items-center justify-center mt-3'>
        <ButtonCommon
          variant="primary"
          size ="large"
          onClick={() => onSave(selected)}
          icon={<Check size={17} />}
        >
          Guardar
        </ButtonCommon>
      </div>
    </div>
  );
}