import React, { useState } from 'react';
import { X, ChevronLeft, ChevronRight, Copy, Check, Printer, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react';
import type { PageNoteData } from '../types';

interface PageNoteDrawerProps {
  data: PageNoteData | null;
  isOpen: boolean;
  onClose: () => void;
  onNavigatePage: (docId: number, targetPage: number) => void;
  highlightQuery?: string;
}

export const PageNoteDrawer: React.FC<PageNoteDrawerProps> = ({
  data,
  isOpen,
  onClose,
  onNavigatePage,
  highlightQuery = '',
}) => {
  const [copied, setCopied] = useState(false);
  const [zoom, setZoom] = useState(1.0);

  if (!isOpen || !data) return null;

  const handleCopy = async () => {
    try {
      const cleaned = data.content
        .split('\n')
        .map((l) => {
          if (l.trim() === '[Table]') return '';
          if (!l.includes('|')) return l;
          const rawCells = l.split('|').map((c) => c.trim()).filter(Boolean);
          const deduped: string[] = [];
          for (const c of rawCells) {
            const norm = c.replace(/\s+/g, ' ');
            if (deduped.length === 0 || deduped[deduped.length - 1].replace(/\s+/g, ' ') !== norm) {
              deduped.push(c);
            }
          }
          return deduped.join(' | ');
        })
        .filter(Boolean)
        .join('\n');

      await navigator.clipboard.writeText(cleaned || data.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const handlePrint = () => {
    window.print();
  };

  const adjustZoom = (delta: number) => {
    setZoom((prev) => Math.min(1.8, Math.max(0.6, Math.round((prev + delta) * 10) / 10)));
  };

  const resetZoom = () => setZoom(1.0);

  // Render paragraphs with heading detection and clinical highlighter
  const renderMiniPageContent = () => {
    if (!data.content || !data.content.trim()) {
      return (
        <div className="text-center py-16 text-slate-400 italic">
          (This page contains no extractable text or is a blank / graphic-only page)
        </div>
      );
    }

    const cleanTokens = highlightQuery
      .replace(/[*"']/g, '')
      .split(/\s+/)
      .filter((w) => w.length > 1 && !['AND', 'OR', 'NOT'].includes(w.toUpperCase()));

    const highlightText = (text: string) => {
      if (cleanTokens.length === 0) return text;
      const escaped = cleanTokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
      const regex = new RegExp(`(${escaped})`, 'gi');
      const parts = text.split(regex);

      return parts.map((part, i) => {
        if (cleanTokens.some((t) => t.toLowerCase() === part.toLowerCase())) {
          return (
            <mark
              key={i}
              className="bg-amber-200 text-amber-950 px-1 py-0.5 rounded font-semibold shadow-xs"
            >
              {part}
            </mark>
          );
        }
        return part;
      });
    };

    const paragraphs = data.content.split(/\n\s*\n/);

    return (
      <div className="space-y-4">
        {paragraphs.map((p, idx) => {
          const clean = p.trim();
          if (!clean) return null;

          const lines = clean.split('\n').map((l) => l.trim()).filter(Boolean);
          const isTable = clean.startsWith('[Table]') || lines.some((l) => l.includes('|'));

          if (isTable) {
            const rowLines = lines.filter((l) => l !== '[Table]');
            return (
              <div key={idx} className="my-3 overflow-x-auto rounded-lg border border-slate-300 bg-slate-50/70 shadow-2xs">
                <table className="w-full text-left text-xs sm:text-sm border-collapse">
                  <tbody>
                    {rowLines.map((line, rIdx) => {
                      const rawCells = line.split('|').map((c) => c.trim()).filter(Boolean);
                      const deduped: string[] = [];
                      for (const c of rawCells) {
                        const norm = c.replace(/\s+/g, ' ');
                        if (deduped.length === 0 || deduped[deduped.length - 1].replace(/\s+/g, ' ') !== norm) {
                          deduped.push(c);
                        }
                      }
                      if (deduped.length === 0) return null;
                      return (
                        <tr
                          key={rIdx}
                          className="border-b border-slate-200 last:border-b-0 hover:bg-white transition-colors"
                        >
                          {deduped.map((c, cIdx) => {
                            const isLabel = cIdx === 0 && (c.endsWith(':') || deduped.length > 1);
                            return (
                              <td
                                key={cIdx}
                                className={`p-2 sm:p-2.5 align-top text-slate-800 border-r border-slate-200 last:border-r-0 ${
                                  isLabel ? 'font-semibold text-slate-900 bg-slate-100/70 whitespace-nowrap' : ''
                                }`}
                              >
                                {highlightText(c)}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          }

          const isHeading =
            clean.length < 85 &&
            (/^(?:[0-9]+[.)]|table|figure|section|abstract|introduction|methods|results|discussion|conclusion|references|guideline|background)/i.test(clean) ||
              (clean === clean.toUpperCase() && clean.length > 4));

          if (isHeading) {
            return (
              <h4
                key={idx}
                className="font-sans font-bold text-slate-900 text-base sm:text-lg mt-5 mb-1.5 border-l-3 border-sky-600 pl-2.5 tracking-tight"
              >
                {highlightText(clean)}
              </h4>
            );
          }

          return (
            <p
              key={idx}
              className="font-serif text-slate-800 text-sm sm:text-base leading-relaxed text-justify"
            >
              {highlightText(clean)}
            </p>
          );
        })}
      </div>
    );
  };

  const isArchive = data.filename.includes('#') || (data as any).is_archive;
  const ext = data.filename.split('.').pop()?.toUpperCase() || 'DOC';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-slate-950/85 backdrop-blur-md transition-opacity">
      {/* Backdrop click */}
      <div className="absolute inset-0" onClick={onClose} />

      {/* Modal / Sheet Container */}
      <div className="relative w-full max-w-3xl h-[94vh] sm:h-[90vh] bg-slate-900 border border-slate-700/80 rounded-2xl sm:rounded-3xl shadow-2xl flex flex-col overflow-hidden animate-slide-up z-10 safe-bottom">
        {/* Topbar */}
        <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between shrink-0 bg-slate-900/90 gap-2">
          <div className="flex items-center space-x-2.5 min-w-0">
            <span className="px-2 py-0.5 rounded text-[10px] font-extrabold uppercase tracking-wider bg-sky-500 text-slate-950 shrink-0">
              {ext}
            </span>
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-slate-100 truncate">
                {data.filename}
              </h3>
              <p className="text-[11px] text-slate-400">
                Mini Page Preview &bull; Page {data.page_number} of {data.total_pages}
              </p>
            </div>
          </div>

          {/* Action Toolbar */}
          <div className="flex items-center space-x-1.5 shrink-0">
            {/* Zoom Controls */}
            <div className="hidden sm:flex items-center bg-slate-800 border border-slate-700 rounded-xl px-1.5 py-0.5 space-x-1 text-xs">
              <button
                onClick={() => adjustZoom(-0.1)}
                className="p-1 text-slate-400 hover:text-slate-100"
                title="Zoom Out"
              >
                <ZoomOut className="w-3.5 h-3.5" />
              </button>
              <span className="font-mono text-[11px] text-sky-400 px-1">
                {Math.round(zoom * 100)}%
              </span>
              <button
                onClick={() => adjustZoom(0.1)}
                className="p-1 text-slate-400 hover:text-slate-100"
                title="Zoom In"
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={resetZoom}
                className="p-1 text-slate-400 hover:text-slate-100"
                title="Reset Zoom"
              >
                <RotateCcw className="w-3 h-3" />
              </button>
            </div>

            <button
              onClick={handlePrint}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors hidden sm:block"
              title="Print / Save Page"
            >
              <Printer className="w-4 h-4" />
            </button>
            <button
              onClick={handleCopy}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
              title="Copy Page Text"
            >
              {copied ? <Check className="w-4 h-4 text-teal-400" /> : <Copy className="w-4 h-4" />}
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
              title="Close (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Stepper Toolbar */}
        <div className="px-4 py-2 border-b border-slate-800 bg-slate-900/60 flex items-center justify-between shrink-0 text-xs">
          <button
            onClick={() => onNavigatePage(data.document_id, data.page_number - 1)}
            disabled={data.page_number <= 1}
            className="flex items-center space-x-1 px-3 py-1 rounded-xl bg-slate-800 border border-slate-700 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-700 transition-colors text-slate-300"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span>Prev Page</span>
          </button>

          <span className="font-mono text-xs px-3 py-1 rounded-full bg-slate-800/90 text-slate-300 border border-slate-700/80">
            Page {data.page_number} / {data.total_pages}
          </span>

          <button
            onClick={() => onNavigatePage(data.document_id, data.page_number + 1)}
            disabled={data.page_number >= data.total_pages}
            className="flex items-center space-x-1 px-3 py-1 rounded-xl bg-slate-800 border border-slate-700 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-700 transition-colors text-slate-300"
          >
            <span>Next Page</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Workbench: Centered Paper Sheet Canvas */}
        <div className="flex-1 overflow-y-auto overflow-x-auto bg-slate-950 p-4 sm:p-8 flex justify-center items-start">
          <div
            className="w-full max-w-xl min-h-[620px] bg-white text-slate-900 rounded-sm shadow-2xl p-6 sm:p-10 border border-slate-300 flex flex-col justify-between transition-transform duration-150 origin-top"
            style={{ transform: `scale(${zoom})` }}
          >
            {/* Running Header */}
            <div>
              <div className="flex items-center justify-between border-b-1.5 border-slate-900 pb-2 mb-6 text-[10px] sm:text-xs font-semibold text-slate-600 tracking-wider">
                <div className="flex items-center space-x-2 truncate">
                  <span className="text-sky-700 font-bold">📄 DOCUMENT ARCHIVE</span>
                  <span className="text-slate-400">•</span>
                  <span className="truncate">{data.filename.toUpperCase()}</span>
                </div>
                <div className="shrink-0 pl-2">
                  <span>PAGE {data.page_number}</span>
                </div>
              </div>

              {/* Sheet Body Content */}
              {renderMiniPageContent()}
            </div>

            {/* Running Footer */}
            <div className="flex items-center justify-between border-t border-slate-300 pt-3 mt-8 text-[10px] text-slate-500 font-mono">
              <span className="truncate max-w-[200px]">{data.filename}</span>
              <span className="font-bold text-slate-900">
                — Page {data.page_number} of {data.total_pages} —
              </span>
              <span>DOCUMENT PREVIEW</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
