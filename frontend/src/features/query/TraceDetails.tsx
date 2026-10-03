/**
 * The trace: what each stage of the pipeline did for one answer.
 *
 * Collapsed by default, because the answer is what the reader came for, and open on demand
 * when the answer is surprising. It shows the request id, so a report from a user can be
 * matched to the backend's log lines for exactly this request.
 */

import type { ReactNode } from 'react'

import type { QueryTrace } from '../../api/types'
import { formatCount, formatMs, formatScore } from '../../lib/format'

export function TraceDetails({
  trace,
  citations,
  outcome,
}: {
  trace: QueryTrace
  citations: number
  outcome: string
}): ReactNode {
  const { retrieval, context, generation } = trace

  return (
    <details className="state" style={{ background: 'transparent' }}>
      <summary style={{ cursor: 'pointer' }}>Trace</summary>
      <div className="trace" style={{ marginTop: '0.6rem' }}>
        <div className="trace__group">
          <h4>Retrieval</h4>
          <dl>
            <dt>Candidates</dt>
            <dd>{formatCount(retrieval.candidates)}</dd>
            <dt>Above threshold</dt>
            <dd>{formatCount(retrieval.above_threshold)}</dd>
            <dt>Used</dt>
            <dd>{formatCount(retrieval.used)}</dd>
            <dt>top-k</dt>
            <dd>{formatCount(retrieval.top_k)}</dd>
            <dt>min score</dt>
            <dd>{formatScore(retrieval.min_score)}</dd>
            <dt>Reranked</dt>
            <dd>{retrieval.reranked ? (retrieval.reranker ?? 'yes') : 'no'}</dd>
            <dt>Missing chunks</dt>
            <dd>{formatCount(retrieval.missing_chunks)}</dd>
            <dt>Duration</dt>
            <dd>{formatMs(retrieval.duration_ms)}</dd>
          </dl>
        </div>

        <div className="trace__group">
          <h4>Context</h4>
          <dl>
            <dt>Passages sent</dt>
            <dd>{formatCount(context.passages)}</dd>
            <dt>Characters</dt>
            <dd>{formatCount(context.chars)}</dd>
            <dt>Dropped by budget</dt>
            <dd>{formatCount(context.skipped)}</dd>
            <dt>Truncated</dt>
            <dd>{context.truncated ? 'yes' : 'no'}</dd>
            <dt>Citations</dt>
            <dd>{formatCount(citations)}</dd>
          </dl>
        </div>

        <div className="trace__group">
          <h4>Generation</h4>
          <dl>
            {/* No generator ran when there was no evidence, so there is nothing to report. */}
            <dt>Model</dt>
            <dd>{generation ? generation.model : 'not reached'}</dd>
            <dt>Kind</dt>
            <dd>{generation ? generation.kind : '—'}</dd>
            <dt>Duration</dt>
            <dd>{generation ? formatMs(generation.duration_ms) : '—'}</dd>
            <dt>Outcome</dt>
            <dd>{outcome}</dd>
          </dl>
        </div>

        <div className="trace__group">
          <h4>Request</h4>
          <dl>
            <dt>Request id</dt>
            <dd className="mono">{trace.request_id ?? '—'}</dd>
            <dt>Total</dt>
            <dd>{formatMs(trace.total_duration_ms)}</dd>
          </dl>
        </div>
      </div>
    </details>
  )
}
