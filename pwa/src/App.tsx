import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Header } from './components/Header';
import { SearchBar } from './components/SearchBar';
import { QuickFilters } from './components/QuickFilters';
import { SearchResults } from './components/SearchResults';
import { PageNoteDrawer } from './components/PageNoteDrawer';
import { DatabaseModal } from './components/DatabaseModal';
import { InstallPrompt } from './components/InstallPrompt';
import { sqliteService } from './services/sqlite/sqliteService';
import type { DatabaseStats, SearchResponse, PageNoteData } from './types';

export const App: React.FC = () => {
  const [query, setQuery] = useState('');
  const [expandSynonyms, setExpandSynonyms] = useState(true);
  const [currentExtension, setCurrentExtension] = useState('all');
  const [activeTopic, setActiveTopic] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(false);
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  const [searchResponse, setSearchResponse] = useState<SearchResponse>({
    query: '',
    parsed_fts: '',
    items: [],
    total_matches: 0,
    total_pages: 0,
    current_page: 1,
    execution_time_ms: 0,
    synonyms_applied: [],
  });

  const [stats, setStats] = useState<DatabaseStats>({
    doc_count: 0,
    page_count: 0,
    paragraph_count: 0,
    db_size_bytes: 0,
    synonym_count: 0,
    storage_type: 'memory',
    is_loaded: false,
    filename: 'medical_search.db',
  });

  const [pageNote, setPageNote] = useState<PageNoteData | null>(null);
  const [isPageNoteOpen, setIsPageNoteOpen] = useState(false);
  const [isDbModalOpen, setIsDbModalOpen] = useState(false);

  // Online / Offline listener
  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Initialize SQLite WASM and load OPFS database on startup
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        await sqliteService.init();
        const currentStats = await sqliteService.getStats();
        if (mounted) {
          setStats(currentStats);
        }
      } catch (err) {
        console.error('[App] SQLite WASM init error:', err);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // Search execution
  const executeSearch = useCallback(
    async (searchQuery: string, page: number = 1) => {
      if (!sqliteService.isReady()) {
        return;
      }
      setIsLoading(true);
      try {
        const resp = await sqliteService.search(searchQuery, page, 20, {
          extension: currentExtension,
          expandSynonyms,
          sortBy: 'relevance',
        });
        setSearchResponse(resp);
      } catch (err) {
        console.error('[App] Search error:', err);
      } finally {
        setIsLoading(false);
      }
    },
    [currentExtension, expandSynonyms]
  );

  // Debounced search on query or filter change
  const debounceTimer = useRef<number | null>(null);
  useEffect(() => {
    if (debounceTimer.current) {
      window.clearTimeout(debounceTimer.current);
    }
    debounceTimer.current = window.setTimeout(() => {
      executeSearch(query, 1);
    }, 180);
    return () => {
      if (debounceTimer.current) window.clearTimeout(debounceTimer.current);
    };
  }, [query, executeSearch]);

  // Topic click handler
  const handleSelectTopic = (topic: string) => {
    setActiveTopic(topic);
    setQuery(topic);
  };

  // Open Page Note drawer
  const handleOpenPageNote = async (docId: number, pageNum: number) => {
    try {
      const note = await sqliteService.getPageNote(docId, pageNum);
      if (note) {
        setPageNote(note);
        setIsPageNoteOpen(true);
      }
    } catch (err) {
      console.error('[App] Failed to load page note:', err);
    }
  };

  // Navigate between pages inside page note drawer
  const handleNavigatePage = async (docId: number, targetPage: number) => {
    try {
      const note = await sqliteService.getPageNote(docId, targetPage);
      if (note) {
        setPageNote(note);
      }
    } catch (err) {
      console.error('[App] Failed to navigate page:', err);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans antialiased selection:bg-sky-500/30 selection:text-sky-200">
      {/* Header */}
      <Header
        stats={stats}
        onOpenDatabaseModal={() => setIsDbModalOpen(true)}
        isOnline={isOnline}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-4xl w-full mx-auto px-4 py-4 sm:py-6 space-y-4">
        {/* Search Bar */}
        <SearchBar
          query={query}
          onQueryChange={(q) => {
            setQuery(q);
            if (activeTopic && q !== activeTopic) setActiveTopic(undefined);
          }}
          expandSynonyms={expandSynonyms}
          onToggleSynonyms={setExpandSynonyms}
          onClear={() => {
            setQuery('');
            setActiveTopic(undefined);
          }}
          isLoading={isLoading}
          totalMatches={searchResponse.total_matches}
        />

        {/* Filters and Cardiology Topics */}
        <QuickFilters
          currentExtension={currentExtension}
          onSelectExtension={(ext) => {
            setCurrentExtension(ext);
            executeSearch(query, 1);
          }}
          onSelectTopic={handleSelectTopic}
          activeTopic={activeTopic}
        />

        {/* Search Results */}
        <SearchResults
          response={searchResponse}
          isLoading={isLoading}
          onOpenPageNote={handleOpenPageNote}
          onPageChange={(page) => executeSearch(query, page)}
        />
      </main>

      {/* Page Note Drawer (Strictly read-only, instant display) */}
      <PageNoteDrawer
        data={pageNote}
        isOpen={isPageNoteOpen}
        onClose={() => setIsPageNoteOpen(false)}
        onNavigatePage={handleNavigatePage}
        highlightQuery={query}
      />

      {/* Database Management & OPFS Modal */}
      <DatabaseModal
        isOpen={isDbModalOpen}
        onClose={() => setIsDbModalOpen(false)}
        stats={stats}
        onLoadDemo={async (onProgress) => {
          const s = await sqliteService.loadBuiltInDatabase(onProgress);
          setStats(s);
          executeSearch(query, 1);
        }}
        onImportFile={async (bytes, filename) => {
          const s = await sqliteService.importDatabaseFile(bytes, filename);
          setStats(s);
          executeSearch(query, 1);
        }}
        onClearDb={async () => {
          await sqliteService.clearDatabase();
          const s = await sqliteService.getStats();
          setStats(s);
          setSearchResponse({
            query: '',
            parsed_fts: '',
            items: [],
            total_matches: 0,
            total_pages: 0,
            current_page: 1,
            execution_time_ms: 0,
            synonyms_applied: [],
          });
        }}
      />

      {/* Mobile PWA Install Prompt Banner */}
      <InstallPrompt />
    </div>
  );
};
