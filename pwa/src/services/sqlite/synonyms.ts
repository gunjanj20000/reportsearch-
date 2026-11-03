/**
 * Cardiology Synonym Dictionary and Transparent Query Expansion Engine.
 * Matches the Phase 2 interventional cardiology terminology.
 */

export const DEFAULT_CARDIOLOGY_SYNONYMS: Record<string, string> = {
  LM: 'Left Main',
  CTO: 'Chronic Total Occlusion',
  ELCA: 'Excimer Laser Coronary Atherectomy',
  IVUS: 'Intravascular Ultrasound',
  OCT: 'Optical Coherence Tomography',
  IVL: 'Intravascular Lithotripsy',
  ISR: 'In-Stent Restenosis',
  TAVI: 'Transcatheter Aortic Valve Implantation',
  TAVR: 'Transcatheter Aortic Valve Replacement',
  CABG: 'Coronary Artery Bypass Grafting',
  PCI: 'Percutaneous Coronary Intervention',
  FFR: 'Fractional Flow Reserve',
  iFR: 'Instantaneous Wave-Free Ratio',
  DES: 'Drug-Eluting Stent',
  BMS: 'Bare-Metal Stent',
  DCB: 'Drug-Coated Balloon',
  MLA: 'Minimum Lumen Area',
  MSA: 'Minimal Stent Area',
  EEL: 'External Elastic Lamina',
  LAD: 'Left Anterior Descending',
  LCx: 'Left Circumflex',
  RCA: 'Right Coronary Artery',
  TCFA: 'Thin-Cap Fibroatheroma',
  MACE: 'Major Adverse Cardiac Events',
  DAPT: 'Dual Antiplatelet Therapy',
};

// Build reverse map for full terms back to acronyms
const REVERSE_MAP: Record<string, string> = {};
for (const [acronym, full] of Object.entries(DEFAULT_CARDIOLOGY_SYNONYMS)) {
  REVERSE_MAP[full.toUpperCase()] = acronym;
}

export function expandCardiologyQuery(query: string): {
  expandedQuery: string;
  synonymsApplied: Array<{ term: string; expansion: string }>;
} {
  const clean = query.trim();
  if (!clean) return { expandedQuery: clean, synonymsApplied: [] };

  const tokens = clean.match(/"[^"]+"|\b[\w-]+\b|[^\s\w"-]/g) || [clean];
  const applied: Array<{ term: string; expansion: string }> = [];
  const parts: string[] = [];

  let i = 0;
  while (i < tokens.length) {
    const token = tokens[i];

    // Skip quoted phrases or boolean keywords
    if (token.startsWith('"') || ['AND', 'OR', 'NOT', 'NEAR'].includes(token.toUpperCase())) {
      parts.push(token);
      i++;
      continue;
    }

    // Try multi-word phrases (3 words, then 2 words)
    let matchedMulti = false;
    for (const lookahead of [4, 3, 2]) {
      if (i + lookahead <= tokens.length) {
        const candidatePhrase = tokens.slice(i, i + lookahead).join(' ');
        const upper = candidatePhrase.toUpperCase();

        if (REVERSE_MAP[upper]) {
          const acronym = REVERSE_MAP[upper];
          parts.push(`("${candidatePhrase}" OR "${acronym}")`);
          applied.push({ term: candidatePhrase, expansion: acronym });
          i += lookahead;
          matchedMulti = true;
          break;
        }
      }
    }
    if (matchedMulti) continue;

    // Single word check
    const upperToken = token.toUpperCase();
    if (DEFAULT_CARDIOLOGY_SYNONYMS[upperToken]) {
      const full = DEFAULT_CARDIOLOGY_SYNONYMS[upperToken];
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
