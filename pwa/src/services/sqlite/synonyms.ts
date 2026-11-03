/**
 * Document Synonym Dictionary and Transparent Query Expansion Engine.
 * Dynamically expands abbreviations and terms based on active database synonyms.
 */

export const DEFAULT_CARDIOLOGY_SYNONYMS: Record<string, string> = {};
export const DEFAULT_SYNONYMS: Record<string, string> = {};

export function expandQueryWithSynonyms(
  query: string,
  synonymsMap: Record<string, string> = DEFAULT_SYNONYMS
): {
  expandedQuery: string;
  synonymsApplied: Array<{ term: string; expansion: string }>;
} {
  const clean = query.trim();
  if (!clean || Object.keys(synonymsMap).length === 0) {
    return { expandedQuery: clean, synonymsApplied: [] };
  }

  // Reverse mapping for expansion -> acronym
  const reverseMap: Record<string, string> = {};
  for (const [acronym, full] of Object.entries(synonymsMap)) {
    reverseMap[full.toUpperCase()] = acronym;
  }

  const tokens = clean.match(/"[^"]+"|\b[\w-]+\b|[^\s\w"-]/g) || [clean];
  const applied: Array<{ term: string; expansion: string }> = [];
  const parts: string[] = [];

  let i = 0;
  while (i < tokens.length) {
    const token = tokens[i];

    // Skip quoted phrases or boolean operators
    if (token.startsWith('"') || ['AND', 'OR', 'NOT', 'NEAR'].includes(token.toUpperCase())) {
      parts.push(token);
      i++;
      continue;
    }

    // Check multi-word phrases (up to 4 words)
    let matchedMulti = false;
    for (const lookahead of [4, 3, 2]) {
      if (i + lookahead <= tokens.length) {
        const candidatePhrase = tokens.slice(i, i + lookahead).join(' ');
        const upper = candidatePhrase.toUpperCase();

        if (reverseMap[upper]) {
          const acronym = reverseMap[upper];
          parts.push(`("${candidatePhrase}" OR "${acronym}")`);
          applied.push({ term: candidatePhrase, expansion: acronym });
          i += lookahead;
          matchedMulti = true;
          break;
        }
      }
    }
    if (matchedMulti) continue;

    // Single token check
    const upperToken = token.toUpperCase();
    if (synonymsMap[upperToken]) {
      const full = synonymsMap[upperToken];
      parts.push(`("${token}" OR "${full}")`);
      applied.push({ term: token, expansion: full });
      i++;
      continue;
    }

    parts.push(token);
    i++;
  }

  return {
    expandedQuery: parts.join(' '),
    synonymsApplied: applied,
  };
}

export function expandCardiologyQuery(
  query: string,
  synonymsMap: Record<string, string> = DEFAULT_CARDIOLOGY_SYNONYMS
): {
  expandedQuery: string;
  synonymsApplied: Array<{ term: string; expansion: string }>;
} {
  return expandQueryWithSynonyms(query, synonymsMap);
}
