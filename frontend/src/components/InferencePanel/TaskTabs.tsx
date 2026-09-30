import type { ModelTask } from '../../types';

interface TaskTabsProps {
  activeTask: ModelTask;
  onChange: (task: ModelTask) => void;
}

const TASK_LABELS: Record<ModelTask, string> = {
  localization: 'Localización (YOLO)',
  classification: 'Clasificación',
  ocr: 'OCR',
  anomaly: 'Anomalía',
};

const TASKS: ModelTask[] = ['localization', 'classification', 'ocr', 'anomaly'];

export function TaskTabs({ activeTask, onChange }: TaskTabsProps) {
  return (
    <div className="flex gap-2" role="tablist" aria-label="Tipo de inferencia">
      {TASKS.map((task) => {
        const isActive = task === activeTask;
        return (
          <button
            key={task}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(task)}
            className={`h-9 px-4 rounded-lg text-[13px] font-semibold border cursor-pointer transition-colors ${
              isActive
                ? 'bg-[#2f6fe4] border-[#2f6fe4] text-white'
                : 'bg-white border-[#e2e5ea] text-[#1f2430] hover:bg-[#f1f2f4]'
            }`}
          >
            {TASK_LABELS[task]}
          </button>
        );
      })}
    </div>
  );
}
