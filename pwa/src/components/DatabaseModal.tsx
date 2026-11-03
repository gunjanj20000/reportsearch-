import React, { useState, useRef } from 'react';
import { X, HardDrive, Upload, Trash2, Download, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react';
import type { DatabaseStats } from '../types';

interface DatabaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  stats: DatabaseStats;
  onLoadDemo: (onProgress: (pct: number) => void) => Promise<void>;
  onImportFile: (fileBytes: Uint8Array, filename: string) => Promise<void>;
  onClearDb: () => Promise<void>;
}

export const DatabaseModal: React.FC<DatabaseModalProps> = ({
  isOpen,
  onClose,
  stats,
  onLoadDemo,
  onImportFile,
  onClearDb,
}) => {
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const handleDemoClick = async () => {
    try {
      setLoading(true);
      setErrorMsg(null);
      setStatusMsg('Downloading & decompressing built-in cardiology database...');
      await onLoadDemo((pct) => setProgress(pct));
      setStatusMsg('Database initialized successfully in OPFS!');
      setTimeout(() => {
        setStatusMsg(null);
        setProgress(null);
      }, 2500);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to load demo database.');
    } finally {
      setLoading(false);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setLoading(true);
      setErrorMsg(null);
      setStatusMsg(`Importing ${file.name}...`);
      const buf = await file.arrayBuffer();
      await onImportFile(new Uint8Array(buf), file.name);
      setStatusMsg(`Successfully imported ${file.name} into OPFS!`);
      setTimeout(() => setStatusMsg(null), 2500);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to import database file.');
    } finally {
      setLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleClear = async () => {
    if (!window.confirm('Clear offline database from storage? You will need to reload or import again.')) {
      return;
    }
    try {
      setLoading(true);
      await onClearDb();
      setStatusMsg('Database cleared from storage.');
      setTimeout(() => setStatusMsg(null), 2000);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to clear database.');
    } finally {
      setLoading(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm">
      <div className="relative w-full max-w-lg bg-slate-900 border border-slate-700/80 rounded-3xl shadow-2xl overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/90">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-xl bg-teal-500/15 border border-teal-400/30 flex items-center justify-center text-teal-400">
              <HardDrive className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100">
                SQLite WASM + OPFS Storage
              </h3>
              <p className="text-[11px] text-slate-400">
                Origin Private File System (Mobile Offline Storage)
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto text-xs sm:text-sm">
          {/* Status / Error alerts */}
          {statusMsg && (
            <div className="p-3 rounded-xl bg-teal-500/15 border border-teal-500/30 text-teal-300 flex items-center space-x-2 text-xs">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{statusMsg}</span>
            </div>
          )}
          {errorMsg && (
            <div className="p-3 rounded-xl bg-rose-500/15 border border-rose-500/30 text-rose-300 flex items-center space-x-2 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Current Database Stats Card */}
          <div className="p-4 rounded-2xl bg-slate-950/70 border border-slate-800 space-y-3">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-300 text-xs uppercase tracking-wider">
                Active Index Status
              </span>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                  stats.is_loaded
                    ? 'bg-teal-500/20 text-teal-300 border border-teal-500/30'
                    : 'bg-slate-800 text-slate-400'
                }`}
              >
                {stats.is_loaded ? `${stats.storage_type.toUpperCase()} Active` : 'No Database'}
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 font-mono text-center">
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800/80">
                <div className="text-base font-bold text-sky-400">{stats.doc_count}</div>
                <div className="text-[10px] text-slate-400 font-sans mt-0.5">Documents</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800/80">
                <div className="text-base font-bold text-teal-400">{stats.page_count}</div>
                <div className="text-[10px] text-slate-400 font-sans mt-0.5">Pages</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800/80">
                <div className="text-base font-bold text-indigo-400">{stats.paragraph_count}</div>
                <div className="text-[10px] text-slate-400 font-sans mt-0.5">Paragraphs</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800/80">
                <div className="text-base font-bold text-slate-200">
                  {formatBytes(stats.db_size_bytes)}
                </div>
                <div className="text-[10px] text-slate-400 font-sans mt-0.5">Database Size</div>
              </div>
            </div>
          </div>

          {/* Progress Bar */}
          {progress !== null && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-[11px] text-slate-400 font-mono">
                <span>Loading into OPFS</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-sky-500 to-teal-400 transition-all duration-200"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Action 1: 1-Tap Load Built-in Demo DB */}
          <div className="space-y-2">
            <button
              onClick={handleDemoClick}
              disabled={loading}
              className="w-full flex items-center justify-center space-x-2 py-3 px-4 rounded-2xl bg-gradient-to-r from-sky-500 to-teal-500 hover:from-sky-400 hover:to-teal-400 text-slate-950 font-bold text-xs sm:text-sm shadow-lg shadow-sky-500/20 active:scale-98 transition-all disabled:opacity-50"
            >
              {loading ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              <span>1-Tap Load Built-in Cardiology Database</span>
            </button>
            <p className="text-[11px] text-slate-400 text-center">
              Bundles 147 clinical trial documents (206 KB compressed via Zstandard).
            </p>
          </div>

          {/* Action 2: File Picker for Custom .db or .db.zst */}
          <div className="pt-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".db,.sqlite,.sqlite3,.zst"
              onChange={handleFileChange}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={loading}
              className="w-full flex items-center justify-center space-x-2 py-2.5 px-4 rounded-2xl bg-slate-800 hover:bg-slate-700/80 border border-slate-700 text-slate-200 font-semibold text-xs active:scale-98 transition-all disabled:opacity-50"
            >
              <Upload className="w-4 h-4 text-sky-400" />
              <span>Import Custom Database (.db or .db.zst)</span>
            </button>
          </div>

          {/* Action 3: Clear Database */}
          {stats.is_loaded && (
            <div className="pt-2 border-t border-slate-800">
              <button
                onClick={handleClear}
                disabled={loading}
                className="w-full flex items-center justify-center space-x-1.5 py-2 px-3 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-400 text-xs font-medium transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Clear Database from Storage</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
