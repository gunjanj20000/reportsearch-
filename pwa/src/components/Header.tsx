import React from 'react';
import { Database, HardDrive, Wifi, WifiOff } from 'lucide-react';
import type { DatabaseStats } from '../types';

interface HeaderProps {
  stats: DatabaseStats;
  onOpenDatabaseModal: () => void;
  isOnline: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  stats,
  onOpenDatabaseModal,
  isOnline,
}) => {
  return (
    <header className="sticky top-0 z-30 bg-slate-900/90 backdrop-blur-md border-b border-slate-800 px-4 py-3 safe-top">
      <div className="max-w-4xl mx-auto flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center space-x-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-sky-500 to-teal-400 p-0.5 flex items-center justify-center shadow-lg shadow-sky-500/20">
            <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
              <span className="text-sky-400 font-bold text-lg leading-none">⚕</span>
            </div>
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-white flex items-center gap-1.5">
              MedSearch <span className="text-xs px-1.5 py-0.5 rounded-full bg-sky-500/10 text-sky-400 font-medium border border-sky-500/20">PWA</span>
            </h1>
            <p className="text-[11px] text-slate-400 hidden sm:block">
              Offline Interventional Cardiology Full-Text Search
            </p>
          </div>
        </div>

        {/* Right Status Pill & DB Button */}
        <div className="flex items-center space-x-2">
          {/* Online/Offline status */}
          <div className="hidden sm:flex items-center space-x-1 text-xs px-2 py-1 rounded-full bg-slate-800/80 border border-slate-700/60 text-slate-400">
            {isOnline ? (
              <>
                <Wifi className="w-3.5 h-3.5 text-teal-400" />
                <span>Online</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3.5 h-3.5 text-amber-400" />
                <span>Offline Mode</span>
              </>
            )}
          </div>

          {/* Database management trigger */}
          <button
            onClick={onOpenDatabaseModal}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all shadow-sm border ${
              stats.is_loaded
                ? 'bg-slate-800/90 hover:bg-slate-700 border-sky-500/30 text-sky-300'
                : 'bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/30 text-amber-300 animate-pulse'
            }`}
            title="Manage SQLite WASM Database and OPFS Storage"
          >
            {stats.storage_type === 'opfs' ? (
              <HardDrive className="w-3.5 h-3.5 text-teal-400" />
            ) : (
              <Database className="w-3.5 h-3.5 text-sky-400" />
            )}
            <span>
              {stats.is_loaded
                ? `${stats.doc_count} Docs (${stats.storage_type.toUpperCase()})`
                : 'Load Database'}
            </span>
          </button>
        </div>
      </div>
    </header>
  );
};
