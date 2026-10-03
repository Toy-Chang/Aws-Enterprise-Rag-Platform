/**
 * One knowledge base: its documents, and the box you ask questions in.
 *
 * Ingestion is asynchronous — an upload returns `pending` and a background worker parses,
 * chunks and embeds it — so the document list polls while anything is in flight and stops as
 * soon as nothing is. That is the only polling in the UI, and it exists because the backend
 * genuinely defers the work.
 */

import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError, asApiError } from '../../api/client'
import { api } from '../../api/endpoints'
import type { DocumentMetadata, DocumentStatus } from '../../api/types'
import { ConfirmButton } from '../../components/ConfirmButton'
import { EmptyState, ErrorState, Loading } from '../../components/states'
import { formatBytes, formatCount, formatTimestamp } from '../../lib/format'
import { useAsync } from '../../lib/useAsync'
import { QueryPanel } from '../query/QueryPanel'
import { DocumentPassages } from './DocumentPassages'

const STATUS_BADGE: Record<DocumentStatus, { label: string; className: string }> = {
  pending: { label: 'pending', className: 'badge badge--muted' },
  processing: { label: 'processing', className: 'badge badge--warn' },
  ready: { label: 'ready', className: 'badge badge--ok' },
  failed: { label: 'failed', className: 'badge badge--error' },
}

const IN_FLIGHT: DocumentStatus[] = ['pending', 'processing']

function StatusBadge({ status }: { status: DocumentStatus }): ReactNode {
  const badge = STATUS_BADGE[status]
  return <span className={badge.className}>{badge.label}</span>
}

type Tab = 'documents' | 'ask'

export function KnowledgeBasePage(): ReactNode {
  const { knowledgeBaseId = '' } = useParams()
  const knowledgeBase = useAsync(
    (signal) => api.getKnowledgeBase(knowledgeBaseId, signal),
    [knowledgeBaseId],
  )
  const documents = useAsync(
    (signal) => api.listDocuments(knowledgeBaseId, signal),
    [knowledgeBaseId],
  )

  const [chosenTab, setChosenTab] = useState<Tab | null>(null)
  const [expandedDocumentId, setExpandedDocumentId] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<ApiError | null>(null)
  const [actionError, setActionError] = useState<ApiError | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const list = documents.data ?? []
  const inFlight = list.some((document) => IN_FLIGHT.includes(document.status))
  const reloadDocuments = documents.reload

  useEffect(() => {
    if (!inFlight) {
      return
    }
    const timer = setInterval(reloadDocuments, 1500)
    return () => {
      clearInterval(timer)
    }
  }, [inFlight, reloadDocuments])

  // Before the operator picks a tab: documents for an empty knowledge base, the question box
  // once there is something to ask about.
  const tab: Tab = chosenTab ?? (list.length === 0 && !documents.loading ? 'documents' : 'ask')

  async function upload(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!file) {
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      await api.uploadDocument(knowledgeBaseId, file)
      setFile(null)
      if (fileInput.current) {
        fileInput.current.value = ''
      }
      reloadDocuments()
    } catch (thrown) {
      setUploadError(asApiError(thrown))
    } finally {
      setUploading(false)
    }
  }

  async function reprocess(document: DocumentMetadata): Promise<void> {
    setActionError(null)
    try {
      await api.reprocessDocument(knowledgeBaseId, document.id)
      reloadDocuments()
    } catch (thrown) {
      setActionError(asApiError(thrown))
    }
  }

  async function remove(document: DocumentMetadata): Promise<void> {
    setActionError(null)
    try {
      await api.deleteDocument(knowledgeBaseId, document.id)
      if (expandedDocumentId === document.id) {
        setExpandedDocumentId(null)
      }
      reloadDocuments()
    } catch (thrown) {
      setActionError(asApiError(thrown))
    }
  }

  return (
    <section>
      <p className="app__subtitle">
        <Link to="/">← All knowledge bases</Link>
      </p>

      {knowledgeBase.loading ? <Loading label="Loading knowledge base…" /> : null}
      {knowledgeBase.error ? (
        <ErrorState error={knowledgeBase.error} onRetry={knowledgeBase.reload} />
      ) : null}

      {knowledgeBase.data ? (
        <>
          <h1>{knowledgeBase.data.name}</h1>
          <p className="card__hint">
            {knowledgeBase.data.description ?? 'No description.'} Created{' '}
            {formatTimestamp(knowledgeBase.data.created_at)}.
          </p>
        </>
      ) : null}

      <div className="nav" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'ask'}
          className={tab === 'ask' ? 'nav__link nav__link--active' : 'nav__link'}
          onClick={() => {
            setChosenTab('ask')
          }}
        >
          Ask a question
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'documents'}
          className={tab === 'documents' ? 'nav__link nav__link--active' : 'nav__link'}
          onClick={() => {
            setChosenTab('documents')
          }}
        >
          Documents{list.length > 0 ? ` (${formatCount(list.length)})` : ''}
        </button>
      </div>

      {tab === 'ask' ? <QueryPanel knowledgeBaseId={knowledgeBaseId} /> : null}

      {tab === 'documents' ? (
        <>
          <div className="card">
            <div className="card__header">
              <h2>Upload a document</h2>
            </div>
            <p className="card__hint">
              PDF, Markdown or plain text. Ingestion runs in the background: the document
              appears as <code>pending</code> and becomes <code>ready</code> when its passages
              are indexed.
            </p>
            <form className="row" onSubmit={(event) => void upload(event)}>
              <div className="field">
                <label htmlFor="document-file">File</label>
                <input
                  id="document-file"
                  ref={fileInput}
                  type="file"
                  accept=".pdf,.md,.markdown,.txt,.text"
                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                    setFile(event.target.files?.[0] ?? null)
                  }}
                />
              </div>
              <button type="submit" className="button button--primary" disabled={!file || uploading}>
                {uploading ? 'Uploading…' : 'Upload'}
              </button>
            </form>
            {uploadError ? <ErrorState error={uploadError} /> : null}
          </div>

          <div className="card">
            <div className="card__header">
              <h2>Documents</h2>
              <div className="row">
                {inFlight ? <span className="badge badge--muted">ingesting…</span> : null}
                <button type="button" className="button button--small" onClick={reloadDocuments}>
                  Refresh
                </button>
              </div>
            </div>

            {actionError ? <ErrorState error={actionError} /> : null}
            {documents.loading ? <Loading label="Loading documents…" /> : null}
            {documents.error ? (
              <ErrorState error={documents.error} onRetry={reloadDocuments} />
            ) : null}

            {!documents.loading && !documents.error && list.length === 0 ? (
              <EmptyState title="No documents yet">
                <p>Upload one above; it will be parsed, split into passages and indexed.</p>
              </EmptyState>
            ) : null}

            {list.length > 0 ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Status</th>
                      <th className="numeric">Passages</th>
                      <th className="numeric">Size</th>
                      <th>Updated</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((document) => (
                      <tr key={document.id}>
                        <td>
                          {document.name}
                          <div className="mono" style={{ color: 'var(--text-muted)' }}>
                            {document.content_type ?? 'unknown type'} · v{document.version}
                          </div>
                          {document.error_message ? (
                            <div style={{ color: 'var(--error)' }}>{document.error_message}</div>
                          ) : null}
                        </td>
                        <td>
                          <StatusBadge status={document.status} />
                        </td>
                        <td className="numeric">{formatCount(document.chunk_count)}</td>
                        <td className="numeric">{formatBytes(document.size_bytes)}</td>
                        <td>{formatTimestamp(document.updated_at)}</td>
                        <td>
                          <div className="row">
                            <button
                              type="button"
                              className="button button--small"
                              onClick={() => {
                                setExpandedDocumentId((current) =>
                                  current === document.id ? null : document.id,
                                )
                              }}
                            >
                              {expandedDocumentId === document.id ? 'Hide' : 'Passages'}
                            </button>
                            <button
                              type="button"
                              className="button button--small"
                              onClick={() => void reprocess(document)}
                            >
                              Reprocess
                            </button>
                            <ConfirmButton
                              label="Delete"
                              confirmLabel="Delete it"
                              onConfirm={() => remove(document)}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>

          {expandedDocumentId ? (
            <DocumentPassages
              knowledgeBaseId={knowledgeBaseId}
              documentId={expandedDocumentId}
              onClose={() => {
                setExpandedDocumentId(null)
              }}
            />
          ) : null}
        </>
      ) : null}
    </section>
  )
}
