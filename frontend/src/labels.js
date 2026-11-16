// Display names for values the API returns.
export const DOC_TYPES = { purchase_order: 'Purchase order', invoice: 'Invoice', unknown: 'Unknown' }

// One-line explanations for the Ask page options (ids come from /options).
export const CHUNKER_HELP = {
  structure: 'Our chunker: one chunk per clause or section; tables kept whole with their header row.',
  hybrid: "Docling's HybridChunker: splits by document structure up to a token limit.",
}

export const METHOD_HELP = {
  dense: 'Vector search: chunks whose meaning is closest to the question.',
  keyword: 'Full-text search: chunks containing the words of the question.',
  hybrid: 'Dense and keyword results merged into one ranking.',
  rerank: 'Dense top 20, re-ordered by a model that reads question and chunk together.',
  dense_ids: 'Dense, but if the question names a document number (e.g. PO/2026-27/0204), only documents with that number.',
  dense_intent:
    'Recommended. Number filter, plus an LLM decides whether the answer is in a PO or an invoice and searches only that type. Falls back to the number filter when unsure.',
}

export const DOCUMENT_HELP = 'All documents, or only the one you pick (then no filters are used).'
