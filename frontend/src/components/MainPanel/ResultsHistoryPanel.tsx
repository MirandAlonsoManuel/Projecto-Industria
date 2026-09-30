import type { InspectionResult, Timestamp } from '../../types/index';

export interface ResultHistoryItem {
  frameId: string;
  result: InspectionResult;
  timestamp: Timestamp;
  thumbnailUrl?: string;
}

interface ResultsHistoryPanelProps {
  results: ResultHistoryItem[];
}

function formatRelativeTime(timestamp: Timestamp): string {
  const seconds = Math.round((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}m`;
}

export function ResultsHistoryPanel({ results }: ResultsHistoryPanelProps) {
  return (
    <aside className="bg-white border border-[#e2e5ea] rounded-[10px] py-3.5 px-4 flex flex-col min-h-0">
      <p className="text-xs font-semibold uppercase tracking-[0.04em] text-gray-500 mb.2.5">
        Últimos resultados
      </p>
      <div className="flex flex-col gap-2.5 overflow-y-auto">
        {results.map((item) => (
          <div key={item.frameId} className="border border-[#f1f2f4] rounded-lg overflow-hidden">
            <div className="h-22.5 bg-[#f1f2f4] flex items-center justify-center">
              {item.thumbnailUrl ? (
                <img src={item.thumbnailUrl} alt={`Frame ${item.frameId}`} />
              ) : (
                <span className="text-[11px] text-[#9aa3af]">{item.frameId}</span>
              )}
            </div>
            <div className="flex justify-between items-center py-1.5 px-2">
              <span
                className={`${'text-[11px] font-bold py-0.5 px-2 rounded-full'} ${item.result === 'ok' ? 'bg-[rgba(30,158,99,0.12)] text-[#1e9e63]' : 'text-[11px] font-bold py-0.5 px-2 rounded-full bg-[rgba(214,69,69,0.12)] text-[#d64545]'}`}
              >
                {item.result}
              </span>
              <span className="text-[11px] text-[#9aa3af]">
                {formatRelativeTime(item.timestamp)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
