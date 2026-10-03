/**
 * The passages a document was split into, in index order.
 *
 * This is the view that makes retrieval explainable without any tooling: you can see exactly
 * what the knowledge base contains, where each passage came from in the original text (its
 * heading path, page and character offsets), which is the same information a citation
 * carries.
 */

import type { ReactNode } from 'react'

import { api } from '../../api/endpoints'
import { EmptyState, ErrorState, Loading } from '../../components/states'
import { formatCount } from '../../lib/format'
import { useAsync } from '../../lib/useAsync'

function headingLabel(headingPath: string[]): string {
  return headingPath.length > 0 ? headingPath.join(' › ') : 'no heading'
}

export function DocumentPassages({
  knowledgeBaseId,
  documentId,
  onClose,
}: {
  knowledgeBaseId: string
  documentId: string
  onClose: () => void
}): ReactNode {
  const chunks = useAsync(
    (signal) => api.listChunks(knowledgeBaseId, documentId, signal),
    [knowledgeBaseId, documentId],
  )
  const list = chunks.data ?? []

  return (
    <div className="card">
      <div className="card__header">
        <h2>Indexed passages</h2>
        <div className="row">
          <span className="card__hint" style={{ margin: 0 }}>
            {list.length > 0 ? `${formatCount(list.length)} passages` : ''}
          </span>
          <button type="button" className="button button--small" onClick={onClose}>
            Close
          </button>
        </div>
      </div>

      {chunks.loading ? <Loading label="Loading passages…" /> : null}
      {chunks.error ? <ErrorState error={chunks.error} onRetry={chunks.reload} /> : null}
      {!chunks.loading && !chunks.error && list.length === 0 ? (
        <EmptyState title="No passages">
          <p>
            Nothing has been indexed from this document yet. A document that failed to parse
            reports the reason in its row.
          </p>
        </EmptyState>
      ) : null}

      <ol style={{ paddingLeft: '1.1rem', margin: 0 }}>
        {list.map((chunk) => (
          <li key={chunk.id} style={{ marginBottom: '0.75rem' }}>
            <div className="citation__head">
              <span className="mono">
                #{chunk.chunk_index} · {headingLabel(chunk.heading_path)}
                {chunk.page_number !== null ? ` · page ${chunk.page_number}` : ''}
              </span>
              <span className="mono">
                chars {formatCount(chunk.char_start)}–{formatCount(chunk.char_end)}
              </span>
            </div>
            <p className="citation__snippet">{chunk.content}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}
