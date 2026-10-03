/**
 * One typed function per backend endpoint.
 *
 * Paths are built from encoded segments, so an identifier that contains a slash or a space
 * cannot escape its position in the URL. Nothing here decides how a call looks in the UI;
 * that is the components' job.
 */

import { request } from './client'
import type {
  Chunk,
  DocumentMetadata,
  EvaluationRequest,
  EvaluationResponse,
  KnowledgeBase,
  Liveness,
  MetricsResponse,
  QueryResponse,
} from './types'

const segment = (value: string): string => encodeURIComponent(value)
const knowledgeBases = '/api/v1/knowledge-bases'
const documentsOf = (knowledgeBaseId: string): string =>
  `${knowledgeBases}/${segment(knowledgeBaseId)}/documents`
const documentOf = (knowledgeBaseId: string, documentId: string): string =>
  `${documentsOf(knowledgeBaseId)}/${segment(documentId)}`

export interface QueryPayload {
  question: string
  top_k?: number
  min_score?: number
}

export const api = {
  /** Liveness, used by the header to show whether the API is reachable. */
  liveness: (signal?: AbortSignal): Promise<Liveness> =>
    request('/health', signal ? { signal } : {}),

  listKnowledgeBases: (signal?: AbortSignal): Promise<KnowledgeBase[]> =>
    request(knowledgeBases, signal ? { signal } : {}),

  createKnowledgeBase: (payload: {
    name: string
    description?: string | null
  }): Promise<KnowledgeBase> =>
    request(knowledgeBases, { method: 'POST', json: payload }),

  getKnowledgeBase: (knowledgeBaseId: string, signal?: AbortSignal): Promise<KnowledgeBase> =>
    request(`${knowledgeBases}/${segment(knowledgeBaseId)}`, signal ? { signal } : {}),

  deleteKnowledgeBase: (knowledgeBaseId: string): Promise<void> =>
    request(`${knowledgeBases}/${segment(knowledgeBaseId)}`, { method: 'DELETE' }),

  listDocuments: (knowledgeBaseId: string, signal?: AbortSignal): Promise<DocumentMetadata[]> =>
    request(documentsOf(knowledgeBaseId), signal ? { signal } : {}),

  /** `file` is required by the endpoint; the browser sets the multipart boundary. */
  uploadDocument: (knowledgeBaseId: string, file: File): Promise<DocumentMetadata> => {
    const body = new FormData()
    body.append('file', file)
    return request(documentsOf(knowledgeBaseId), { method: 'POST', body })
  },

  getDocument: (
    knowledgeBaseId: string,
    documentId: string,
    signal?: AbortSignal,
  ): Promise<DocumentMetadata> =>
    request(documentOf(knowledgeBaseId, documentId), signal ? { signal } : {}),

  listChunks: (
    knowledgeBaseId: string,
    documentId: string,
    signal?: AbortSignal,
  ): Promise<Chunk[]> =>
    request(`${documentOf(knowledgeBaseId, documentId)}/chunks`, signal ? { signal } : {}),

  reprocessDocument: (
    knowledgeBaseId: string,
    documentId: string,
  ): Promise<DocumentMetadata> =>
    request(`${documentOf(knowledgeBaseId, documentId)}/reprocess`, { method: 'POST' }),

  deleteDocument: (knowledgeBaseId: string, documentId: string): Promise<void> =>
    request(documentOf(knowledgeBaseId, documentId), { method: 'DELETE' }),

  query: (
    knowledgeBaseId: string,
    payload: QueryPayload,
    signal?: AbortSignal,
  ): Promise<QueryResponse> =>
    request(`${knowledgeBases}/${segment(knowledgeBaseId)}/query`, {
      method: 'POST',
      json: payload,
      ...(signal ? { signal } : {}),
    }),

  metrics: (signal?: AbortSignal): Promise<MetricsResponse> =>
    request('/api/v1/metrics', signal ? { signal } : {}),

  /** Runs the whole pipeline server-side; the corpus is removed before the response. */
  runEvaluation: (payload: EvaluationRequest): Promise<EvaluationResponse> =>
    request('/api/v1/evaluations', { method: 'POST', json: payload }),
}
