/**
 * OPFS (Origin Private File System) Storage Manager with IndexedDB Fallback.
 * Provides true persistent storage for SQLite WASM databases on mobile Safari (iOS) and Chrome (Android).
 */

const DB_NAME = 'medsearch_storage_v1';
const STORE_NAME = 'databases';
export const DEFAULT_DB_FILENAME = 'medical_search.db';

export function isOpfsSupported(): boolean {
  return typeof navigator !== 'undefined' &&
    Boolean(navigator.storage && typeof navigator.storage.getDirectory === 'function');
}

// -------------------------------------------------------------
// IndexedDB Fallback Implementation
// -------------------------------------------------------------
function openIndexedDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function saveToIndexedDB(key: string, data: Uint8Array): Promise<void> {
  const db = await openIndexedDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const req = store.put(data, key);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

async function loadFromIndexedDB(key: string): Promise<Uint8Array | null> {
  try {
    const db = await openIndexedDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.get(key);
      req.onsuccess = () => resolve(req.result instanceof Uint8Array ? req.result : (req.result ? new Uint8Array(req.result) : null));
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

async function deleteFromIndexedDB(key: string): Promise<void> {
  try {
    const db = await openIndexedDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const req = store.delete(key);
      req.onsuccess = () => resolve();
      req.onerror = () => resolve();
    });
  } catch {
    // ignore
  }
}

// -------------------------------------------------------------
// OPFS Implementation
// -------------------------------------------------------------
export async function saveDatabaseToStorage(
  filename: string = DEFAULT_DB_FILENAME,
  data: Uint8Array
): Promise<'opfs' | 'idb'> {
  if (isOpfsSupported()) {
    try {
      const root = await navigator.storage.getDirectory();
      const fileHandle = await root.getFileHandle(filename, { create: true });
      
      // Modern Safari (iOS 16.4+) & Chrome (Android 102+)
      if ('createWritable' in fileHandle) {
        const writable = await (fileHandle as any).createWritable();
        await writable.write(data);
        await writable.close();
        return 'opfs';
      }
    } catch (e) {
      console.warn('[OPFS] Direct write failed, falling back to IndexedDB:', e);
    }
  }

  // Fallback to IndexedDB
  await saveToIndexedDB(filename, data);
  return 'idb';
}

export async function loadDatabaseFromStorage(
  filename: string = DEFAULT_DB_FILENAME
): Promise<{ data: Uint8Array; storageType: 'opfs' | 'idb' } | null> {
  // 1. Try OPFS first
  if (isOpfsSupported()) {
    try {
      const root = await navigator.storage.getDirectory();
      const fileHandle = await root.getFileHandle(filename, { create: false });
      const file = await fileHandle.getFile();
      const buf = await file.arrayBuffer();
      if (buf.byteLength > 0) {
        return { data: new Uint8Array(buf), storageType: 'opfs' };
      }
    } catch {
      // file not present in OPFS or inaccessible, check IDB
    }
  }

  // 2. Check IndexedDB
  const idbData = await loadFromIndexedDB(filename);
  if (idbData && idbData.byteLength > 0) {
    return { data: idbData, storageType: 'idb' };
  }

  return null;
}

export async function deleteDatabaseFromStorage(
  filename: string = DEFAULT_DB_FILENAME
): Promise<void> {
  if (isOpfsSupported()) {
    try {
      const root = await navigator.storage.getDirectory();
      await root.removeEntry(filename);
    } catch {
      // ignore if missing
    }
  }
  await deleteFromIndexedDB(filename);
}

export async function getStorageStats(): Promise<{
  usageBytes: number;
  quotaBytes: number;
  opfsAvailable: boolean;
}> {
  let usage = 0;
  let quota = 0;
  const opfsAvailable = isOpfsSupported();

  if (navigator.storage && navigator.storage.estimate) {
    try {
      const est = await navigator.storage.estimate();
      usage = est.usage || 0;
      quota = est.quota || 0;
    } catch {
      // ignore
    }
  }

  return { usageBytes: usage, quotaBytes: quota, opfsAvailable };
}
