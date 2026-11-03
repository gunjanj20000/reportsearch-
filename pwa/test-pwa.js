import assert from 'node:assert';
import { expandQueryWithSynonyms } from './src/services/sqlite/synonyms.ts';
import { parseFtsQuery } from './src/services/sqlite/queryParser.ts';

console.log('Testing PWA Services (Node.js test suite)...');

// 1. Test Document Synonym Expansion with dynamic dictionary
const testSynonyms = {
  CTO: 'Chronic Total Occlusion',
  LM: 'Left Main',
  IVUS: 'Intravascular Ultrasound'
};

const synRes1 = expandQueryWithSynonyms('CTO', testSynonyms);
assert.strictEqual(synRes1.expandedQuery, '("CTO" OR "Chronic Total Occlusion")');
assert.strictEqual(synRes1.synonymsApplied.length, 1);
assert.strictEqual(synRes1.synonymsApplied[0].term, 'CTO');
console.log('✔ Document synonym acronym expansion: CTO -> Chronic Total Occlusion');

const synRes2 = expandQueryWithSynonyms('Left Main', testSynonyms);
assert.strictEqual(synRes2.expandedQuery, '("Left Main" OR "LM")');
assert.strictEqual(synRes2.synonymsApplied[0].term, 'Left Main');
console.log('✔ Reverse synonym expansion: Left Main -> LM');

const synRes3 = expandQueryWithSynonyms('"CTO" AND IVUS', testSynonyms);
assert(synRes3.expandedQuery.includes('"CTO"'));
assert(synRes3.expandedQuery.includes('("IVUS" OR "Intravascular Ultrasound")'));
console.log('✔ Quoted terms preserved during synonym expansion');

// 2. Test FTS5 Query Parser
const q1 = parseFtsQuery('stent thrombosis');
assert.strictEqual(q1, 'stent AND thrombosis');
console.log('✔ Implicit AND insertion');

const q2 = parseFtsQuery('stent -thrombosis');
assert.strictEqual(q2, 'stent NOT "thrombosis"');
console.log('✔ Exclusion translation: -thrombosis -> NOT "thrombosis"');

const q3 = parseFtsQuery('"left main');
assert.strictEqual(q3, '"left main"');
console.log('✔ Balanced unclosed quote');

const q4 = parseFtsQuery('stent* OR balloon');
assert.strictEqual(q4, 'stent* OR balloon');
console.log('✔ Prefix wildcard preserved');

// 3. Test SQLite WASM FTS5 with BM25 & Snippets
import('./node_modules/@sqlite.org/sqlite-wasm/sqlite-wasm/jswasm/sqlite3-node.mjs').then(async (m) => {
  const sqlite3 = await m.default();
  const db = new sqlite3.oo1.DB();
  db.exec(`
    CREATE VIRTUAL TABLE test_fts USING fts5(title, content, tokenize = 'unicode61');
    INSERT INTO test_fts VALUES('Document 1', 'Evaluating technical specification report with details.');
    INSERT INTO test_fts VALUES('Document 2', 'Annual performance review and financial analysis.');
  `);

  const results = [];
  db.exec({
    sql: "SELECT title, snippet(test_fts, -1, '<mark>', '</mark>', '...', 10) as snip, bm25(test_fts) as rank FROM test_fts WHERE test_fts MATCH 'specification' ORDER BY rank ASC;",
    rowMode: 'object',
    callback: (r) => results.push(r)
  });

  assert.strictEqual(results.length, 1);
  assert.strictEqual(results[0].title, 'Document 1');
  assert(results[0].snip.includes('<mark>specification</mark>'));
  console.log('✔ SQLite WASM FTS5 BM25 search & snippet highlighting');
  db.close();

  console.log('\nAll PWA unit tests passed successfully! (7/7)');
}).catch((err) => {
  console.error('SQLite WASM node test error:', err);
  process.exit(1);
});
