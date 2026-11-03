/**
 * Client-Side SQLite FTS5 Query Parser and Sanitizer.
 * Safely converts user search input into robust FTS5 MATCH queries.
 */

export function parseFtsQuery(raw: string): string {
  let query = raw.trim();
  if (!query) return '';

  // 1. Balance unclosed double quotes
  const quoteCount = (query.match(/"/g) || []).length;
  if (quoteCount % 2 !== 0) {
    query += '"';
  }

  // 2. Extract quoted phrases, hyphenated exclusions, and words
  const tokens: string[] = [];
  const regex = /"([^"]+)"|(\bNOT\b|\bAND\b|\bOR\b)|(-[a-zA-Z0-9_*]+)|([a-zA-Z0-9_*]+)/gi;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(query)) !== null) {
    const [full, quoted, boolOp, exclusion, word] = match;

    if (quoted) {
      const cleanInside = quoted.replace(/[*"']/g, ' ').trim();
      if (cleanInside) {
        tokens.push(`"${cleanInside}"`);
      }
    } else if (boolOp) {
      tokens.push(boolOp.toUpperCase());
    } else if (exclusion) {
      const term = exclusion.slice(1).replace(/[^a-zA-Z0-9_*]/g, '').trim();
      if (term) {
        tokens.push('NOT');
        tokens.push(term.includes('*') ? term : `"${term}"`);
      }
    } else if (word) {
      tokens.push(word);
    }
  }

  if (tokens.length === 0) return '';

  // 3. Assemble tokens with implicit AND
  const result: string[] = [];
  const operators = new Set(['AND', 'OR', 'NOT']);

  for (let i = 0; i < tokens.length; i++) {
    const curr = tokens[i];
    const prev = i > 0 ? tokens[i - 1] : null;

    if (operators.has(curr)) {
      // Don't start query with binary operator
      if (result.length === 0 && (curr === 'AND' || curr === 'OR')) {
        continue;
      }
      result.push(curr);
    } else {
      // If previous wasn't an operator, insert implicit AND
      if (prev && !operators.has(prev)) {
        result.push('AND');
      }
      result.push(curr);
    }
  }

  // Drop trailing operators
  while (result.length > 0 && operators.has(result[result.length - 1])) {
    result.pop();
  }

  return result.join(' ');
}
