export interface SearchResultItem {
  document_id: number;
  filename: string;
  extension: string;
  source_path: string;
  file_size: number;
  page_number: number;
  paragraph_number: number;
  doc_title: string;
  rank_score: number;
  snip: string;
  google_drive_url?: string;
  last_indexed?: string;
}

export interface SearchResponse {
  query: string;
  parsed_fts: string;
  items: SearchResultItem[];
  total_matches: number;
  total_pages: number;
  current_page: number;
  execution_time_ms: number;
  synonyms_applied: Array<{ term: string; expansion: string }>;
}

export interface DatabaseStats {
  doc_count: number;
  page_count: number;
  paragraph_count: number;
  db_size_bytes: number;
  synonym_count: number;
  storage_type: 'opfs' | 'idb' | 'memory';
  is_loaded: boolean;
  filename: string;
}

export interface PageNoteData {
  document_id: number;
  filename: string;
  page_number: number;
  total_pages: number;
  content: string;
}

export interface SearchFilters {
  extension: string; // 'all' | '.pdf' | '.docx' | '.txt'
  expandSynonyms: boolean;
  sortBy: 'relevance' | 'title' | 'date';
}
