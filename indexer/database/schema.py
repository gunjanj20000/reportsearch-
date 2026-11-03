"""SQLite and FTS5 Schema definitions."""

import sqlite3

SCHEMA_SQL = """
-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    document_id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    modified_time REAL NOT NULL,
    sha256 TEXT NOT NULL,
    source_path TEXT NOT NULL UNIQUE,
    google_drive_file_id TEXT,
    google_drive_url TEXT,
    page_count INTEGER DEFAULT 0,
    extraction_status TEXT NOT NULL,
    error_message TEXT,
    last_indexed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_source_path ON documents(source_path);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(extraction_status);

-- Document pages table
CREATE TABLE IF NOT EXISTS document_pages (
    page_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    extracted_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_pages_doc_id ON document_pages(document_id);

-- Document paragraphs table
CREATE TABLE IF NOT EXISTS document_paragraphs (
    paragraph_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    paragraph_number INTEGER NOT NULL,
    paragraph_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_paragraphs_doc_id ON document_paragraphs(document_id);

-- Collections table
CREATE TABLE IF NOT EXISTS collections (
    collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_name TEXT NOT NULL UNIQUE,
    description TEXT
);

-- Document collections junction table
CREATE TABLE IF NOT EXISTS document_collections (
    document_id INTEGER NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, collection_id)
);

-- FTS5 Search virtual table with unicode61 tokenizer and remove_diacritics
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    title,
    paragraph_text,
    page_text,
    document_id UNINDEXED,
    page_number UNINDEXED,
    paragraph_number UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Execute DDL statements to set up SQLite relational and FTS5 tables."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
