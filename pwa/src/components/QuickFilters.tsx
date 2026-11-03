import React from 'react';

interface QuickFiltersProps {
  currentExtension: string;
  onSelectExtension: (ext: string) => void;
  onSelectTopic?: (topic: string) => void;
  activeTopic?: string;
}

export const QuickFilters: React.FC<QuickFiltersProps> = ({
  currentExtension,
  onSelectExtension,
}) => {
  const formats = [
    { label: 'All Formats', val: 'all' },
    { label: 'PDF Documents', val: '.pdf' },
    { label: 'Word (.docx)', val: '.docx' },
    { label: 'Legacy Word (.doc)', val: '.doc' },
    { label: 'Plain Text (.txt)', val: '.txt' },
    { label: 'Archives (.zip, .tar)', val: 'archive' },
  ];

  return (
    <div className="space-y-2">
      {/* Format Filter Pills */}
      <div className="flex items-center space-x-1.5 overflow-x-auto no-scrollbar pb-1">
        {formats.map((f) => {
          const isActive = currentExtension === f.val;
          return (
            <button
              key={f.val}
              onClick={() => onSelectExtension(f.val)}
              className={`px-3 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap transition-all border ${
                isActive
                  ? 'bg-slate-800 border-sky-500/50 text-sky-300 shadow-sm'
                  : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:text-slate-300 hover:bg-slate-800/50'
              }`}
            >
              {f.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};
