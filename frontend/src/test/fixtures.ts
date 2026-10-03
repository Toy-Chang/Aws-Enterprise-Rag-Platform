/**
 * Response fixtures that match the backend contract.
 *
 * Each one is a realistic body rather than a minimal object, so a test that reads `trace` or
 * `latency` fails when the contract changes instead of passing against a hollow stub.
 */

import type {
  DocumentMetadata,
  EvaluationResponse,
  KnowledgeBase,
  MetricsResponse,
  QueryResponse,
} from '../api/types'

export function knowledgeBase(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return {
    id: 'kb-1',
    name: 'Platform runbooks',
    description: 'Operational documents',
    created_at: '2026-01-01T09:30:00Z',
    updated_at: '2026-01-01T09:30:00Z',
    ...overrides,
  }
}

export function documentMetadata(overrides: Partial<DocumentMetadata> = {}): DocumentMetadata {
  return {
    id: 'doc-1',
    knowledge_base_id: 'kb-1',
    name: 'incident-response.md',
    content_type: 'text/markdown',
    size_bytes: 1500,
    status: 'ready',
    version: 1,
    chunk_count: 2,
    error_message: null,
    created_at: '2026-01-01T09:31:00Z',
    updated_at: '2026-01-01T09:31:02Z',
    ...overrides,
  }
}

export function answeredQuery(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    knowledge_base_id: 'kb-1',
    question: 'How often do database credentials rotate?',
    outcome: 'answered',
    answer: '[1] Credential rotation\n\nDatabase credentials rotate every ninety days.',
    answer_kind: 'extractive',
    citations: [
      {
        marker: 1,
        document_id: 'doc-1',
        document_name: 'incident-response.md',
        chunk_id: 'chunk-1',
        chunk_index: 2,
        page_number: null,
        heading_path: ['Encryption policy', 'Credential rotation'],
        score: 0.369274,
        rerank_score: null,
        snippet: 'Credential rotation Database credentials rotate every ninety days…',
      },
    ],
    usage: { input_tokens: null, output_tokens: null },
    trace: {
      request_id: 'req-1',
      retrieval: {
        candidates: 3,
        above_threshold: 3,
        used: 1,
        top_k: 5,
        min_score: 0.1,
        reranked: false,
        reranker: null,
        missing_chunks: 0,
        duration_ms: 1.797,
      },
      context: { chars: 472, passages: 1, skipped: 2, truncated: false },
      generation: { model: 'extractive-local', kind: 'extractive', duration_ms: 0.009 },
      total_duration_ms: 2.047,
    },
    ...overrides,
  }
}

export function insufficientEvidence(): QueryResponse {
  return answeredQuery({
    outcome: 'insufficient_evidence',
    answer: null,
    answer_kind: null,
    citations: [],
    trace: {
      request_id: 'req-2',
      retrieval: {
        candidates: 3,
        above_threshold: 0,
        used: 0,
        top_k: 5,
        min_score: 0.1,
        reranked: false,
        reranker: null,
        missing_chunks: 0,
        duration_ms: 1.2,
      },
      context: { chars: 0, passages: 0, skipped: 0, truncated: false },
      // Nothing reached the generator, so there is no stage to report.
      generation: null,
      total_duration_ms: 1.4,
    },
  })
}

export function metricsResponse(overrides: Partial<MetricsResponse> = {}): MetricsResponse {
  return {
    window: 1024,
    counters: {
      'http.requests.total': 6,
      'http.responses.2xx': 5,
      'http.route./knowledge-bases': 1,
      'http.route.unmatched': 1,
      'ingestion.succeeded': 2,
      'query.answered': 3,
      'query.insufficient_evidence': 1,
      'evaluation.runs': 1,
    },
    latencies: {
      query: {
        observed: 4,
        retained: 4,
        mean_ms: 0.7,
        p50_ms: 0.6,
        p95_ms: 1.0,
        max_ms: 1.0,
      },
      ingestion: {
        observed: 2,
        retained: 2,
        mean_ms: 2.1,
        p50_ms: 1.6,
        p95_ms: 4.0,
        max_ms: 4.0,
      },
    },
    ...overrides,
  }
}

export function evaluationResponse(
  overrides: Partial<EvaluationResponse> = {},
): EvaluationResponse {
  return {
    dataset: 'platform-runbooks-smoke',
    temporary_knowledge_base_id: 'b304307e60ed472eb566b34dbca08444',
    k: 5,
    min_score: 0.1,
    documents: 5,
    chunks: 19,
    total_questions: 6,
    answerable: 5,
    unanswerable: 1,
    retrieval: {
      questions: 5,
      k: 5,
      recall_at_k: 1.0,
      precision_at_k: 0.2,
      hit_rate_at_k: 1.0,
      mrr: 1.0,
      ndcg_at_k: 1.0,
    },
    answers: {
      answered: 6,
      insufficient_evidence: 0,
      answerable_answered: 1.0,
      unanswerable_abstained: 0.0,
      citation_precision: 0.26,
      citation_recall: 1.0,
    },
    latency: {
      retrieval_ms: { count: 6, mean: 0.46, minimum: 0.35, p50: 0.4, p95: 0.9, maximum: 0.9 },
      generation_ms: { count: 6, mean: 0.004, minimum: 0.002, p50: 0.004, p95: 0.005, maximum: 0.005 },
      total_ms: { count: 6, mean: 0.726, minimum: 0.61, p50: 0.7, p95: 1.19, maximum: 1.19 },
    },
    issues: [],
    per_question: [
      {
        id: 'credential-rotation',
        question: 'How often do database credentials rotate?',
        answerable: true,
        outcome: 'answered',
        answer_kind: 'extractive',
        citations: 5,
        relevant_chunks: 1,
        retrieved_chunks: 5,
        matched_chunks: 1,
        recall_at_k: 1.0,
        precision_at_k: 0.2,
        reciprocal_rank: 1.0,
        ndcg_at_k: 1.0,
        citation_precision: 0.2,
        citation_recall: 1.0,
        retrieval_ms: 0.35,
        generation_ms: 0.003,
        total_ms: 0.66,
        issues: [],
      },
      {
        id: 'holiday-schedule',
        question: 'What is the company holiday schedule?',
        answerable: false,
        outcome: 'answered',
        answer_kind: 'extractive',
        citations: 5,
        relevant_chunks: 0,
        retrieved_chunks: 5,
        matched_chunks: null,
        // Unscorable: no metric is reported rather than a zero.
        recall_at_k: null,
        precision_at_k: null,
        reciprocal_rank: null,
        ndcg_at_k: null,
        citation_precision: null,
        citation_recall: null,
        retrieval_ms: 0.4,
        generation_ms: 0.004,
        total_ms: 0.7,
        issues: [],
      },
    ],
    ...overrides,
  }
}
