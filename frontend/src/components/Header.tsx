export type AppView = 'monitor' | 'inference';

interface HeaderProps {
  view: AppView;
  onViewChange: (view: AppView) => void;
}

function Header({ view, onViewChange }: HeaderProps) {
  return (
    <header className="w-full h-[60px] flex items-center justify-between px-5 bg-white border-b border-gray-200 box-border">
      <div className="w-[100px] flex items-center">{/* aquí luego va un botón o logo */}</div>

      <h1 className="font-['Inter'] text-[26px] font-semibold text-gray-900 m-0">
        Camera Frontend
      </h1>

      <div className="min-w-[100px] flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => onViewChange('monitor')}
          className={`h-[34px] px-[14px] rounded-lg border font-['Inter'] text-[13px] font-semibold cursor-pointer ${
            view === 'monitor'
              ? 'bg-[#2f6fe4] border-[#2f6fe4] text-white'
              : 'bg-white border-gray-200 text-gray-900'
          }`}
        >
          Monitoreo en vivo
        </button>
        <button
          type="button"
          onClick={() => onViewChange('inference')}
          className={`h-[34px] px-[14px] rounded-lg border font-['Inter'] text-[13px] font-semibold cursor-pointer ${
            view === 'inference'
              ? 'bg-[#2f6fe4] border-[#2f6fe4] text-white'
              : 'bg-white border-gray-200 text-gray-900'
          }`}
        >
          Pruebas de inferencia
        </button>
      </div>
    </header>
  );
}

export default Header;
