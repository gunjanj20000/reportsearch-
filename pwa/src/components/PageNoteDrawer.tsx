import React, { useState } from 'react';
import { X, ChevronLeft, ChevronRight, Copy, Check, FileText, Sparkles } from 'lucide-react';
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

  if (!isOpen || !data) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(data.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  // Highlight search keywords in page text
  const renderHighlightedContent = () => {
    if (!highlightQuery.trim()) {
      return <div className="whitespace-pre-wrap">{data.content}</div>;
    }

    const cleanTokens = highlightQuery
      .replace(/[*"']/g, '')
      .split(/\s+/)
      .filter((w) => w.length > 1 && !['AND', 'OR', 'NOT'].includes(w.toUpperCase()));

    if (cleanTokens.length === 0) {
      return <div className="whitespace-pre-wrap">{data.content}</div>;
    }

    const escaped = cleanTokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    const regex = new RegExp(`(${escaped})`, 'gi');
    const parts = data.content.split(regex);

    return (
      <div className="whitespace-pre-wrap leading-relaxed">
        {parts.map((part, i) => {
          if (cleanTokens.some((t) => t.toLowerCase() === part.toLowerCase())) {
            return (
              <mark
                key={i}
                className="bg-sky-400/30 text-sky-200 px-0.5 rounded font-medium border-b border-sky-400/60"
              >
                {part}
              </mark>
            );
          }
          return part;
        })}
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end sm:justify-center items-center bg-slate-950/80 backdrop-blur-sm transition-opacity">
      {/* Backdrop click */}
      <div className="absolute inset-0" onClick={onClose} />

      {/* Drawer / Modal Container */}
      <div className="relative w-full max-w-2xl max-h-[88vh] sm:max-h-[82vh] bg-slate-900 border border-slate-700/80 rounded-t-3xl sm:rounded-3xl shadow-2xl flex flex-col overflow-hidden animate-slide-up z-10 safe-bottom">
        {/* Mobile handle indicator */}
        <div className="w-12 h-1.5 bg-slate-700 rounded-full mx-auto my-2.5 sm:hidden shrink-0" />

        {/* Drawer Header */}
        <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between shrink-0 bg-slate-900/90">
          <div className="flex items-center space-x-2.5 min-w-0">
            <div className="w-8 h-8 rounded-xl bg-sky-500/15 border border-sky-400/30 flex items-center justify-center text-sky-400 shrink-0">
              <FileText className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-slate-100 truncate">
                {data.filename}
              </h3>
              <p className="text-[11px] text-slate-400 font-mono">
                Page {data.page_number} of {data.total_pages} (Clinical Note)
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-1.5">
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
              title="Close Drawer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Note Body (Scrollable) */}
        <div className="p-5 overflow-y-auto text-xs sm:text-sm text-slate-200 font-mono leading-relaxed bg-slate-950/70 select-text flex-1">
          {renderHighlightedContent()}
        </div>

        {/* Note Footer (Pagination) */}
        <div className="px-5 py-3 border-t border-slate-800 bg-slate-900/90 flex items-center justify-between shrink-0 text-xs text-slate-300">
          <button
            onClick={() => onNavigatePage(data.document_id, data.page_number - 1)}
            disabled={data.page_number <= 1}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-700 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            <span>Prev Page</span>
          </button>

          <span className="font-mono text-xs text-slate-400">
            Page {data.page_number} / {data.total_pages}
          </span>

          <button
            onClick={() => onNavigatePage(data.document_id, data.page_number + 1)}
            disabled={data.page_number >= data.total_pages}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-700 transition-colors"
          >
            <span>Next Page</span>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
