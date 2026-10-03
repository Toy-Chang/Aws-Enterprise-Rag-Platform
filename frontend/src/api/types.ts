/**
 * The backend's HTTP contract, as TypeScript types.
 *
 * These mirror `backend/app/schemas/*.py` field for field. They are hand-written rather
 * than generated: there is no OpenAPI codegen step in this repository, and a generated
 * client that nobody regenerates drifts more quietly than a file that must be edited when
 * the backend changes. Names and optionality follow the Pydantic models exactly, so a
 * mismatch is a type error at the call site rather than a `undefined` at run time.
 *
 * Timestamps arrive as ISO-8601 strings in UTC and are formatted for display only.
 */

export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed'

export type QueryOutcome = 'answered' | 'insufficient_evidence'

export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface DocumentMetadata {
  id: string
  knowledge_base_id: string
  name: string
  content_type: string | null
  size_bytes: number
  status: DocumentStatus
  version: number
  chunk_count: number
  error_message: string | null
  created_at: string
  updated_at: string
}

/** One indexed passage. Offsets are relative to the block the passage came from. */
export interface Chunk {
  id: string
  document_id: string
  chunk_index: number
  content: string
  char_start: number
  char_end: number
  page_number: number | null
  heading_path: string[]
  created_at: string
}

/** A passage the answer was built from. */
export interface Citation {
  marker: number
  document_id: string
  document_name: string
  chunk_id: string
  chunk_index: number
  page_number: number | null
  heading_path: string[]
  score: number
  rerank_score: number | null
  snippet: string
}

export interface Usage {
  input_tokens: number | null
  output_tokens: number | null
}

export interface RetrievalTrace {
  /**
   * Passages the index returned for this query — a count about the call, not the corpus,
   * so a small `top_k` reports a small candidate count even in a large knowledge base.
   */
  candidates: number
  above_threshold: number
  /** Passages retrieval selected; the context budget can still keep some out of the answer. */
  used: number
  top_k: number
  min_score: number
  reranked: boolean
  reranker: string | null
  /** Matches whose chunk had already been deleted; should be zero. */
  missing_chunks: number
  duration_ms: number
}

export interface ContextTrace {
  chars: number
  passages: number
  skipped: number
  truncated: boolean
}

export interface GenerationTrace {
  model: string
  /** `extractive` for passages returned verbatim, `generated` for a model. */
  kind: string
  duration_ms: number
}

export interface QueryTrace {
  request_id: string | null
  retrieval: RetrievalTrace
  context: ContextTrace
  /** Null when nothing reached the generator — no evidence, no generation. */
  generation: GenerationTrace | null
  total_duration_ms: number
}

export interface QueryResponse {
  knowledge_base_id: string
  question: string
  outcome: QueryOutcome
  answer: string | null
  answer_kind: string | null
  citations: Citation[]
  usage: Usage
  trace: QueryTrace
}

/** A latency summary over the samples the backend retained, in milliseconds. */
export interface LatencySummary {
  /** Measurements recorded in total, including those that left the retained window. */
  observed: number
  retained: number
  mean_ms: number
  p50_ms: number
  p95_ms: number
  max_ms: number
}

export interface MetricsResponse {
  window: number
  counters: Record<string, number>
  latencies: Record<string, LatencySummary>
}

export interface EvaluationDocument {
  name: string
  content: string
}

export interface EvaluationLabel {
  document: string
  contains: string
}

export interface EvaluationQuestion {
  id: string
  question: string
  answerable: boolean
  relevant: EvaluationLabel[]
}

export interface EvaluationRequest {
  name: string
  k?: number
  /** Overrides the server's threshold for this run; the report says which one was used. */
  min_score?: number | null
  documents: EvaluationDocument[]
  questions: EvaluationQuestion[]
}

export interface Summary {
  count: number
  mean: number
  minimum: number
  p50: number
  p95: number
  maximum: number
}

export interface RetrievalMetrics {
  questions: number
  k: number
  recall_at_k: number
  precision_at_k: number
  hit_rate_at_k: number
  mrr: number
  ndcg_at_k: number
}

/**
 * A rate is null when its denominator is zero: a dataset with no unanswerable question
 * has not shown that the platform abstains, and 1.0 would claim it from no observations.
 */
export interface AnswerMetrics {
  answered: number
  insufficient_evidence: number
  answerable_answered: number | null
  unanswerable_abstained: number | null
  citation_precision: number | null
  citation_recall: number | null
}

export interface EvaluationLatency {
  retrieval_ms: Summary
  generation_ms: Summary | null
  total_ms: Summary
}

/** One question, what the pipeline did with it, and how it scored. Null means unscorable. */
export interface QuestionResult {
  id: string
  question: string
  answerable: boolean
  outcome: string
  answer_kind: string | null
  citations: number
  relevant_chunks: number
  retrieved_chunks: number
  matched_chunks: number | null
  recall_at_k: number | null
  precision_at_k: number | null
  reciprocal_rank: number | null
  ndcg_at_k: number | null
  citation_precision: number | null
  citation_recall: number | null
  retrieval_ms: number
  generation_ms: number | null
  total_ms: number
  issues: string[]
}

export interface EvaluationResponse {
  dataset: string
  /** Removed before the response was returned; kept for log correlation. */
  temporary_knowledge_base_id: string
  k: number
  min_score: number
  documents: number
  chunks: number
  total_questions: number
  answerable: number
  unanswerable: number
  /** Null when no question had a resolvable label. */
  retrieval: RetrievalMetrics | null
  answers: AnswerMetrics
  latency: EvaluationLatency
  issues: string[]
  per_question: QuestionResult[]
}

/** The single error envelope every non-successful response uses. */
export interface ErrorEnvelope {
  request_id: string
  error: {
    code: string
    message: string
    details: unknown
  }
}

export interface Liveness {
  status: 'ok'
  service: string
  version: string
  environment: string
}

export interface HealthCheck {
  name: string
  status: 'ok' | 'degraded'
  detail: string | null
}

export interface Readiness {
  status: 'ok' | 'degraded'
  service: string
  version: string
  environment: string
  checks: HealthCheck[]
}
