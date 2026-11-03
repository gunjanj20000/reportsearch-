import React, { useRef, useEffect } from 'react';
import { Search, X, Sparkles, Activity } from 'lucide-react';

interface SearchBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  expandSynonyms: boolean;
  onToggleSynonyms: (val: boolean) => void;
  onClear: () => void;
  isLoading: boolean;
  totalMatches: number;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  query,
  onQueryChange,
  expandSynonyms,
  onToggleSynonyms,
  onClear,
  isLoading,
  totalMatches,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus on slash or shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement !== inputRef.current) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="space-y-2.5">
      {/* Search Input Box */}
      <div className="relative group">
        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400 group-focus-within:text-sky-400 transition-colors">
          {isLoading ? (
            <Activity className="w-5 h-5 animate-pulse text-sky-400" />
          ) : (
            <Search className="w-5 h-5" />
          )}
        </div>
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search literature, clinical trials, CTO, stents..."
          className="w-full pl-11 pr-10 py-3.5 bg-slate-900 border border-slate-700/80 rounded-2xl text-slate-100 placeholder-slate-400 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-sky-500/50 focus:border-sky-500 transition-all shadow-inner"
          autoComplete="off"
          autoCorrect="off"
          spellCheck="false"
        />
        {query && (
          <button
            onClick={onClear}
            className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-200 transition-colors"
            title="Clear search"
          >
            <X className="w-4 h-4 bg-slate-800 rounded-full p-0.5" />
          </button>
        )}
      </div>

      {/* Cardiology Synonym Expansion Toggle */}
      <div className="flex items-center justify-between px-1 py-0.5 text-xs">
        <button
          type="button"
          onClick={() => onToggleSynonyms(!expandSynonyms)}
          className={`flex items-center space-x-2 px-3 py-1.5 rounded-full border transition-all ${
            expandSynonyms
              ? 'bg-sky-500/15 border-sky-400/40 text-sky-300 font-medium shadow-sm shadow-sky-500/10'
              : 'bg-slate-800/70 border-slate-700/70 text-slate-400 hover:text-slate-300'
          }`}
          title="Expand clinical acronyms: CTO ↔ Chronic Total Occlusion, LM ↔ Left Main, IVUS, etc."
        >
          <Sparkles className={`w-3.5 h-3.5 ${expandSynonyms ? 'text-sky-400' : 'text-slate-400'}`} />
          <span>Cardiology Synonyms</span>
          <span
            className={`w-2 h-2 rounded-full ${
              expandSynonyms ? 'bg-sky-400 animate-pulse' : 'bg-slate-600'
            }`}
          />
        </button>

        <span className="text-slate-500 text-[11px] font-mono">
          {query ? `${totalMatches} matches` : 'Press / to search'}
        </span>
      </div>
    </div>
  );
};
