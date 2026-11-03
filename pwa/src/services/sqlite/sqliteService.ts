/**
 * SQLite WASM Service with OPFS / IndexedDB Persistence and FTS5 Search.
 */

import sqlite3InitModule from '@sqlite.org/sqlite-wasm';
import { decompress } from 'fzstd';
import {
  saveDatabaseToStorage,
  loadDatabaseFromStorage,
  deleteDatabaseFromStorage,
  DEFAULT_DB_FILENAME,
  isOpfsSupported,
} from '../storage/opfs';
import { parseFtsQuery } from './queryParser';
import { expandCardiologyQuery } from './synonyms';
import type {
  SearchResultItem,
  SearchResponse,
  DatabaseStats,
  PageNoteData,
  SearchFilters,
} from '../../types';

class SqliteService {
  private sqlite3: any = null;
  private db: any = null;
  private isInitializing: boolean = false;
  private storageType: 'opfs' | 'idb' | 'memory' = 'memory';
  private currentDbFilename: string = DEFAULT_DB_FILENAME;
  private initPromise: Promise<void> | null = null;

  public async init(): Promise<void> {
    if (this.db) return;
    if (this.initPromise) return this.initPromise;

    this.initPromise = (async () => {
      try {
        this.isInitializing = true;
        console.log('[SQLite WASM] Initializing module...');
        
        this.sqlite3 = await sqlite3InitModule({
          print: console.log,
          printErr: console.error,
        });

        console.log('[SQLite WASM] Loaded SQLite version:', this.sqlite3.version.libVersion);

        // Check if database is already saved in OPFS or IndexedDB
        const saved = await loadDatabaseFromStorage(this.currentDbFilename);
        if (saved && saved.data.byteLength > 0) {
          console.log(`[SQLite WASM] Found saved database in ${saved.storageType} (${saved.data.byteLength} bytes)`);
          await this.loadDatabaseFromBytes(saved.data, saved.storageType);
        } else {
          console.log('[SQLite WASM] No existing database in storage. Ready for import or demo load.');
        }
      } catch (err) {
        console.error('[SQLite WASM] Initialization error:', err);
        throw err;
      } finally {
        this.isInitializing = false;
      }
    })();

    return this.initPromise;
  }

  public isReady(): boolean {
    return Boolean(this.db);
  }

  public getStorageType(): 'opfs' | 'idb' | 'memory' {
    return this.storageType;
  }

  private async loadDatabaseFromBytes(
    bytes: Uint8Array,
    storageType: 'opfs' | 'idb' | 'memory' = 'memory'
  ): Promise<void> {
    if (!this.sqlite3) {
      await this.init();
    }

    if (this.db) {
      try {
        this.db.close();
      } catch {
        // ignore
      }
      this.db = null;
    }

    try {
      const p = this.sqlite3.wasm.allocFromTypedArray(bytes);
      const newDb = new this.sqlite3.oo1.DB();
      const rc = this.sqlite3.capi.sqlite3_deserialize(
        newDb,
        'main',
        p,
        bytes.byteLength,
        bytes.byteLength,
        this.sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE |
          this.sqlite3.capi.SQLITE_DESERIALIZE_RESIZEABLE
      );

      if (rc !== 0) {
        throw new Error(`sqlite3_deserialize failed with code ${rc}`);
      }

      this.db = newDb;
      this.storageType = storageType;
      console.log(`[SQLite WASM] Successfully loaded database via ${storageType}.`);
    } catch (err) {
      console.error('[SQLite WASM] Failed to deserialize database bytes:', err);
      throw err;
    }
  }

  /**
   * Import database from user-provided file (.db or .db.zst).
   * Automatically decompresses Zstandard archives and persists to OPFS/IndexedDB.
   */
  public async importDatabaseFile(
    fileBytes: Uint8Array,
    filename: string = 'imported_search.db'
  ): Promise<DatabaseStats> {
    await this.init();

    let rawDbBytes: Uint8Array;
    // Check Zstandard magic header: 0x28, 0xB5, 0x2F, 0xFD
    if (
      fileBytes.length >= 4 &&
      fileBytes[0] === 0x28 &&
      fileBytes[1] === 0xb5 &&
      fileBytes[2] === 0x2f &&
      fileBytes[3] === 0xfd
    ) {
      console.log('[SQLite WASM] Detected Zstandard compressed database. Decompressing via fzstd...');
      const t0 = performance.now();
      rawDbBytes = decompress(fileBytes);
      const t1 = performance.now();
      console.log(`[SQLite WASM] Decompressed ${fileBytes.byteLength} -> ${rawDbBytes.byteLength} bytes in ${(t1 - t0).toFixed(1)} ms.`);
    } else {
      rawDbBytes = fileBytes;
    }

    // Persist to OPFS (with IndexedDB fallback)
    const stType = await saveDatabaseToStorage(DEFAULT_DB_FILENAME, rawDbBytes);
    this.currentDbFilename = DEFAULT_DB_FILENAME;

    // Load into SQLite WASM
    await this.loadDatabaseFromBytes(rawDbBytes, stType);

    return this.getStats();
  }

  /**
   * Load the built-in compact cardiology database bundled with the PWA.
   */
  public async loadBuiltInDatabase(onProgress?: (percent: number) => void): Promise<DatabaseStats> {
    await this.init();

    const candidates = ['./medical_search_compact.db.zst', './medical_search_compact.db'];
    let resp: Response | null = null;
    let chosenUrl = '';

    for (const url of candidates) {
      try {
        const r = await fetch(url);
        if (r.ok) {
          resp = r;
          chosenUrl = url;
          break;
        }
      } catch {
        // try next
      }
    }

    if (!resp) {
      throw new Error('Built-in database file not found on server.');
    }

    const contentLength = Number(resp.headers.get('content-length')) || 215000;
    const reader = resp.body?.getReader();

    if (!reader) {
      const buf = await resp.arrayBuffer();
      return this.importDatabaseFile(new Uint8Array(buf), chosenUrl);
    }

    const chunks: Uint8Array[] = [];
    let received = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        chunks.push(value);
        received += value.length;
        if (onProgress && contentLength > 0) {
          onProgress(Math.min(100, Math.round((received / contentLength) * 100)));
        }
      }
    }

    const merged = new Uint8Array(received);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    return this.importDatabaseFile(merged, chosenUrl);
  }

  /**
   * Execute full-text search against the SQLite FTS5 table with BM25 ranking.
   */
  public async search(
    rawQuery: string,
    page: number = 1,
    pageSize: number = 20,
    filters: SearchFilters = { extension: 'all', expandSynonyms: false, sortBy: 'relevance' }
  ): Promise<SearchResponse> {
    const t0 = performance.now();
    const cleanQuery = rawQuery.trim();

    if (!this.db || !cleanQuery) {
      return {
        query: rawQuery,
        parsed_fts: '',
        items: [],
        total_matches: 0,
        total_pages: 0,
        current_page: page,
        execution_time_ms: 0,
        synonyms_applied: [],
      };
    }

    // 1. Synonym expansion
    let targetQuery = cleanQuery;
    let synonymsApplied: Array<{ term: string; expansion: string }> = [];

    if (filters.expandSynonyms) {
      const expResult = expandCardiologyQuery(cleanQuery);
      targetQuery = expResult.expandedQuery;
      synonymsApplied = expResult.synonymsApplied;
    }

    // 2. FTS5 query parsing
    let parsedFts = parseFtsQuery(targetQuery);
    if (!parsedFts) {
      parsedFts = `"${cleanQuery.replace(/"/g, '')}"`;
    }

    // 3. Build query and filters
    const whereClauses: string[] = ['s.search_index MATCH ?'];
    const bindParams: any[] = [parsedFts];

    if (filters.extension && filters.extension !== 'all') {
      whereClauses.push('d.extension = ?');
      bindParams.push(filters.extension.toLowerCase());
    }

    const whereSql = whereClauses.join(' AND ');

    // 4. Count total matches
    const countSql = `
      SELECT COUNT(*) as total
      FROM search_index s
      JOIN documents d ON d.document_id = s.document_id
      WHERE ${whereSql};
    `;

    let totalMatches = 0;
    try {
      this.db.exec({
        sql: countSql,
        bind: bindParams,
        rowMode: 'object',
        callback: (row: any) => {
          totalMatches = Number(row.total || 0);
        },
      });
    } catch (e: any) {
      console.warn('[SQLite WASM] FTS5 count error with query:', parsedFts, e);
      // Fallback to phrase search
      parsedFts = `"${cleanQuery.replace(/"/g, '')}"`;
      bindParams[0] = parsedFts;
      this.db.exec({
        sql: countSql,
        bind: bindParams,
        rowMode: 'object',
        callback: (row: any) => {
          totalMatches = Number(row.total || 0);
        },
      });
    }

    const totalPages = Math.ceil(totalMatches / pageSize);
    const offset = Math.max(0, (page - 1) * pageSize);

    // Sort order
    let orderClause = 'ORDER BY rank_score ASC';
    if (filters.sortBy === 'title') {
      orderClause = 'ORDER BY doc_title ASC';
    } else if (filters.sortBy === 'date') {
      orderClause = 'ORDER BY d.last_indexed DESC';
    }

    // 5. Data query with BM25 and snippets
    const dataSql = `
      SELECT
        d.document_id,
        d.filename,
        d.extension,
        d.source_path,
        d.file_size,
        d.google_drive_url,
        d.last_indexed,
        COALESCE(s.title, d.filename) as doc_title,
        s.page_number,
        s.paragraph_number,
        bm25(s.search_index, 5.0, 2.0, 1.0) as rank_score,
        snippet(s.search_index, -1, '<mark class="highlight">', '</mark>', '...', 25) as snip
      FROM search_index s
      JOIN documents d ON d.document_id = s.document_id
      WHERE ${whereSql}
      ${orderClause}
      LIMIT ? OFFSET ?;
    `;

    const dataBind = [...bindParams, pageSize, offset];
    const items: SearchResultItem[] = [];

    this.db.exec({
      sql: dataSql,
      bind: dataBind,
      rowMode: 'object',
      callback: (r: any) => {
        items.push({
          document_id: Number(r.document_id),
          filename: String(r.filename || ''),
          extension: String(r.extension || ''),
          source_path: String(r.source_path || ''),
          file_size: Number(r.file_size || 0),
          page_number: Number(r.page_number || 1),
          paragraph_number: Number(r.paragraph_number || 1),
          doc_title: String(r.doc_title || r.filename),
          rank_score: Number(r.rank_score || 0),
          snip: String(r.snip || ''),
          google_drive_url: r.google_drive_url ? String(r.google_drive_url) : undefined,
          last_indexed: r.last_indexed ? String(r.last_indexed) : undefined,
        });
      },
    });

    const t1 = performance.now();

    return {
      query: rawQuery,
      parsed_fts: parsedFts,
      items,
      total_matches: totalMatches,
      total_pages: totalPages,
      current_page: page,
      execution_time_ms: Math.round((t1 - t0) * 10) / 10,
      synonyms_applied: synonymsApplied,
    };
  }

  /**
   * Instant Page Note Loader (Strictly read-only, 0 bytes extra disk storage).
   */
  public async getPageNote(documentId: number, pageNumber: number): Promise<PageNoteData | null> {
    if (!this.db) return null;

    let filename = '';
    let totalPages = 1;

    // Get document metadata
    this.db.exec({
      sql: 'SELECT filename, page_count FROM documents WHERE document_id = ?;',
      bind: [documentId],
      rowMode: 'object',
      callback: (r: any) => {
        filename = String(r.filename);
        totalPages = Math.max(1, Number(r.page_count || 1));
      },
    });

    if (!filename) return null;

    let content = '';

    // Check document_pages table
    this.db.exec({
      sql: 'SELECT extracted_text FROM document_pages WHERE document_id = ? AND page_number = ? LIMIT 1;',
      bind: [documentId, pageNumber],
      rowMode: 'object',
      callback: (r: any) => {
        content = String(r.extracted_text || '');
      },
    });

    // Fallback: assemble from document_paragraphs if document_pages is empty
    if (!content) {
      const parts: string[] = [];
      this.db.exec({
        sql: 'SELECT paragraph_text FROM document_paragraphs WHERE document_id = ? AND page_number = ? ORDER BY paragraph_number ASC;',
        bind: [documentId, pageNumber],
        rowMode: 'object',
        callback: (r: any) => {
          if (r.paragraph_text) parts.push(String(r.paragraph_text));
        },
      });
      content = parts.join('\n\n');
    }

    return {
      document_id: documentId,
      filename,
      page_number: pageNumber,
      total_pages: totalPages,
      content: content || 'No text content extracted for this page.',
    };
  }

  /**
   * Retrieve database and storage statistics.
   */
  public async getStats(): Promise<DatabaseStats> {
    if (!this.db) {
      return {
        doc_count: 0,
        page_count: 0,
        paragraph_count: 0,
        db_size_bytes: 0,
        synonym_count: 0,
        storage_type: this.storageType,
        is_loaded: false,
        filename: this.currentDbFilename,
      };
    }

    let docCount = 0;
    let pageCount = 0;
    let paraCount = 0;
    let synCount = 0;
    let pageCountDb = 0;
    let pageSize = 4096;

    try {
      this.db.exec({
        sql: 'SELECT COUNT(*) as c FROM documents;',
        rowMode: 'object',
        callback: (r: any) => { docCount = Number(r.c); },
      });
    } catch { /* ignore */ }

    try {
      this.db.exec({
        sql: 'SELECT COUNT(*) as c FROM document_pages;',
        rowMode: 'object',
        callback: (r: any) => { pageCount = Number(r.c); },
      });
    } catch { /* ignore */ }

    try {
      this.db.exec({
        sql: 'SELECT COUNT(*) as c FROM document_paragraphs;',
        rowMode: 'object',
        callback: (r: any) => { paraCount = Number(r.c); },
      });
    } catch { /* ignore */ }

    try {
      this.db.exec({
        sql: 'SELECT COUNT(*) as c FROM synonyms;',
        rowMode: 'object',
        callback: (r: any) => { synCount = Number(r.c); },
      });
    } catch { /* ignore */ }

    try {
      this.db.exec({
        sql: 'PRAGMA page_count;',
        rowMode: 'object',
        callback: (r: any) => { pageCountDb = Number(Object.values(r)[0] || 0); },
      });
      this.db.exec({
        sql: 'PRAGMA page_size;',
        rowMode: 'object',
        callback: (r: any) => { pageSize = Number(Object.values(r)[0] || 4096); },
      });
    } catch { /* ignore */ }

    return {
      doc_count: docCount,
      page_count: pageCount,
      paragraph_count: paraCount,
      db_size_bytes: pageCountDb * pageSize,
      synonym_count: synCount,
      storage_type: this.storageType,
      is_loaded: true,
      filename: this.currentDbFilename,
    };
  }

  /**
   * Clear database from storage and reset state.
   */
  public async clearDatabase(): Promise<void> {
    if (this.db) {
      try {
        this.db.close();
      } catch { /* ignore */ }
      this.db = null;
    }
    await deleteDatabaseFromStorage(this.currentDbFilename);
    this.storageType = 'memory';
    console.log('[SQLite WASM] Database deleted from OPFS and state cleared.');
  }
}

export const sqliteService = new SqliteService();
