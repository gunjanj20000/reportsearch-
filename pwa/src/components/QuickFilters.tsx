import React from 'react';

interface QuickFiltersProps {
  currentExtension: string;
  onSelectExtension: (ext: string) => void;
  onSelectTopic: (topic: string) => void;
  activeTopic?: string;
}

const TOPICS = [
  'CTO',
  'Left Main',
  'IVUS',
  'Drug-Eluting Stent',
  'TAVR',
  'OCT',
  'Bifurcation',
  'Atherectomy',
];

export const QuickFilters: React.FC<QuickFiltersProps> = ({
  currentExtension,
  onSelectExtension,
  onSelectTopic,
  activeTopic,
}) => {
  const formats = [
    { label: 'All Formats', val: 'all' },
    { label: 'PDF', val: '.pdf' },
    { label: 'DOCX', val: '.docx' },
    { label: 'TXT', val: '.txt' },
  ];

  return (
    <div className="space-y-2.5">
      {/* Format Pills */}
      <div className="flex items-center space-x-1.5 overflow-x-auto no-scrollbar pb-0.5">
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

      {/* Suggested Cardiology Topic Chips */}
      <div className="flex items-center space-x-1.5 overflow-x-auto no-scrollbar pb-1 text-xs">
        <span className="text-[11px] text-slate-500 uppercase tracking-wider font-semibold pl-1 whitespace-nowrap">
          Topics:
        </span>
        {TOPICS.map((topic) => {
          const isSelected = activeTopic?.toLowerCase() === topic.toLowerCase();
          return (
            <button
              key={topic}
              onClick={() => onSelectTopic(topic)}
              className={`px-2.5 py-1 rounded-lg whitespace-nowrap transition-all border ${
                isSelected
                  ? 'bg-sky-500/20 border-sky-400 text-sky-200 font-medium'
                  : 'bg-slate-900/50 border-slate-800/80 text-slate-400 hover:text-slate-200 hover:border-slate-700'
              }`}
            >
              {topic}
            </button>
          );
        })}
      </div>
    </div>
  );
};
