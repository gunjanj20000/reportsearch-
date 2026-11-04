import React from 'react';
import { FileText, FileCode, BookOpen, Clock, ChevronLeft, ChevronRight, ArrowUpRight } from 'lucide-react';
import type { SearchResponse, SearchResultItem } from '../types';

interface SearchResultsProps {
  response: SearchResponse;
  isLoading: boolean;
  onOpenPageNote: (docId: number, pageNum: number) => void;
  onPageChange: (page: number) => void;
}

function sanitizeSnippet(snipHtml: string): string {
  if (!snipHtml || !snipHtml.includes('|')) return snipHtml;
  return snipHtml
    .split('\n')
    .map((line) => {
      if (!line.includes('|')) return line;
      const parts = line.split('|').map((p) => p.trim());
      const deduped: string[] = [];
      for (const p of parts) {
        if (!p) continue;
        const plain = p.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ');
        if (
          deduped.length === 0 ||
          deduped[deduped.length - 1].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ') !== plain
        ) {
          deduped.push(p);
        }
      }
      if (
        deduped.length > 1 &&
        new Set(deduped.map((c) => c.replace(/<[^>]+>/g, '').replace(/\s+/g, ' '))).size === 1
      ) {
        deduped.length = 1;
      }
      return deduped.join(' | ');
    })
    .join('\n');
}

export const SearchResults: React.FC<SearchResultsProps> = ({
  response,
  isLoading,
  onOpenPageNote,
  onPageChange,
}) => {
  if (isLoading) {
    return (
      <div className="py-16 text-center space-y-3">
        <div className="inline-block w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-slate-400">Searching SQLite FTS5 index...</p>
      </div>
    );
  }

  if (!response.query) {
    return (
      <div className="py-16 text-center space-y-4 max-w-sm mx-auto px-4">
        <div className="w-14 h-14 mx-auto rounded-2xl bg-slate-800/80 border border-slate-700/60 flex items-center justify-center text-sky-400">
          <BookOpen className="w-7 h-7" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-slate-200">
            Instant Offline Document Search
          </h3>
          <p className="text-xs text-slate-400 mt-1 leading-relaxed">
            Search indexed documents, reports, manuals, PDFs, Word files, and archives directly in your browser.
          </p>
        </div>
      </div>
    );
  }

  if (response.items.length === 0) {
    return (
      <div className="py-14 text-center space-y-3 max-w-sm mx-auto px-4">
        <div className="w-12 h-12 mx-auto rounded-2xl bg-slate-800/50 flex items-center justify-center text-slate-400">
          <FileText className="w-6 h-6" />
        </div>
        <h3 className="text-sm font-semibold text-slate-200">No matching documents found</h3>
        <p className="text-xs text-slate-400">
          Try adjusting keywords, checking spelling, or using quotes for exact phrases like <span className="text-sky-300 font-mono">"annual report"</span>.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3.5">
      {/* Search Meta Bar */}
      <div className="flex flex-wrap items-center justify-between text-xs text-slate-400 px-1 gap-2">
        <div className="flex items-center space-x-2">
          <span className="font-semibold text-slate-200">
            {response.total_matches.toLocaleString()} {response.total_matches === 1 ? 'match' : 'matches'}
          </span>
          <span>•</span>
          <span className="flex items-center space-x-1 font-mono text-[11px]">
            <Clock className="w-3 h-3 text-slate-500" />
            <span>{response.execution_time_ms} ms</span>
          </span>
        </div>

        {response.synonyms_applied.length > 0 && (
          <div className="flex items-center space-x-1.5 bg-sky-500/10 border border-sky-500/20 px-2 py-0.5 rounded-full text-[11px] text-sky-300">
            <span>Expanded:</span>
            {response.synonyms_applied.map((s, idx) => (
              <span key={idx} className="font-semibold">
                "{s.term}" ↔ "{s.expansion}"{idx < response.synonyms_applied.length - 1 ? ', ' : ''}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Results List */}
      <div className="space-y-3">
        {response.items.map((item, index) => {
          const isPdf = item.extension.toLowerCase() === '.pdf';
          const isDocx = item.extension.toLowerCase().includes('doc');

          return (
            <article
              key={`${item.document_id}-${item.page_number}-${item.paragraph_number}-${index}`}
              className="group bg-slate-900/90 border border-slate-800/90 hover:border-slate-700/90 rounded-2xl p-4 transition-all hover:shadow-lg hover:shadow-sky-500/5 space-y-2.5"
            >
              {/* Header: Title and Badges */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start space-x-2.5 min-w-0">
                  <div
                    className={`mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase ${
                      isPdf
                        ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
                        : isDocx
                        ? 'bg-blue-500/15 text-blue-300 border border-blue-500/30'
                        : 'bg-slate-700 text-slate-300'
                    }`}
                  >
                    {item.extension.replace('.', '')}
                  </div>
                  <div className="min-w-0">
                    <h4 className="text-sm font-semibold text-slate-100 truncate group-hover:text-sky-300 transition-colors">
                      {item.doc_title || item.filename}
                    </h4>
                    <p className="text-[11px] text-slate-400 truncate font-mono">
                      {item.filename}
                    </p>
                  </div>
                </div>

                {/* Page indicator */}
                <span className="shrink-0 text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700/60">
                  Page {item.page_number}
                </span>
              </div>

              {/* High-contrast Snippet */}
              <div
                className="text-xs text-slate-300 leading-relaxed font-sans snippet-text bg-slate-950/60 p-3 rounded-xl border border-slate-800/60"
                dangerouslySetInnerHTML={{ __html: sanitizeSnippet(item.snip) }}
              />

              {/* Card Footer Actions */}
              <div className="flex items-center justify-between pt-1 text-xs">
                <span className="text-[10px] font-mono text-slate-500">
                  BM25: {Math.abs(item.rank_score).toFixed(2)}
                </span>

                <button
                  onClick={() => onOpenPageNote(item.document_id, item.page_number)}
                  className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/30 text-sky-300 text-xs font-medium transition-all active:scale-95"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  <span>Open Page Note (Page {item.page_number})</span>
                  <ArrowUpRight className="w-3 h-3 text-sky-400" />
                </button>
              </div>
            </article>
          );
        })}
      </div>

      {/* Pagination */}
      {response.total_pages > 1 && (
        <div className="flex items-center justify-between pt-4 pb-8 px-2 text-xs text-slate-400">
          <button
            onClick={() => onPageChange(response.current_page - 1)}
            disabled={response.current_page <= 1}
            className="flex items-center space-x-1 px-3 py-1.5 rounded-xl bg-slate-800/80 border border-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-700 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            <span>Previous</span>
          </button>

          <span className="font-mono text-slate-300">
            Page {response.current_page} of {response.total_pages}
          </span>

          <button
            onClick={() => onPageChange(response.current_page + 1)}
            disabled={response.current_page >= response.total_pages}
            className="flex items-center space-x-1 px-3 py-1.5 rounded-xl bg-slate-800/80 border border-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-700 transition-colors"
          >
            <span>Next</span>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
};
