/**
 * The knowledge bases: what exists, create one, remove one.
 *
 * Creation and deletion are the only writes here, and both surface the backend's own error
 * verbatim — a duplicate name is a `409 CONFLICT` with the name in `details`, and hiding
 * that behind "could not create" would make the operator guess.
 */

import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, asApiError } from '../../api/client'
import { api } from '../../api/endpoints'
import type { KnowledgeBase } from '../../api/types'
import { ConfirmButton } from '../../components/ConfirmButton'
import { EmptyState, ErrorState, Loading } from '../../components/states'
import { formatCount, formatTimestamp } from '../../lib/format'
import { useAsync } from '../../lib/useAsync'

export function KnowledgeBasesPage(): ReactNode {
  const list = useAsync((signal) => api.listKnowledgeBases(signal), [])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<ApiError | null>(null)
  const [actionError, setActionError] = useState<ApiError | null>(null)

  async function create(event: FormEvent): Promise<void> {
    event.preventDefault()
    setCreating(true)
    setCreateError(null)
    try {
      await api.createKnowledgeBase({
        name,
        description: description.trim() === '' ? null : description.trim(),
      })
      setName('')
      setDescription('')
      list.reload()
    } catch (thrown) {
      setCreateError(asApiError(thrown))
    } finally {
      setCreating(false)
    }
  }

  async function remove(knowledgeBase: KnowledgeBase): Promise<void> {
    setActionError(null)
    try {
      await api.deleteKnowledgeBase(knowledgeBase.id)
      list.reload()
    } catch (thrown) {
      setActionError(asApiError(thrown))
    }
  }

  const knowledgeBases = list.data ?? []

  return (
    <section>
      <h1>Knowledge bases</h1>
      <p className="card__hint">
        A knowledge base owns a set of documents and the passages indexed from them. Answers
        are built only from the knowledge base you ask.
      </p>

      <div className="card">
        <div className="card__header">
          <h2>Create</h2>
        </div>
        <form className="row" onSubmit={(event) => void create(event)}>
          <div className="field">
            <label htmlFor="kb-name">Name</label>
            <input
              id="kb-name"
              value={name}
              maxLength={120}
              required
              placeholder="Platform runbooks"
              onChange={(event) => {
                setName(event.target.value)
              }}
            />
          </div>
          <div className="field">
            <label htmlFor="kb-description">Description (optional)</label>
            <input
              id="kb-description"
              value={description}
              maxLength={1000}
              placeholder="Operational documents used by the on-call rotation"
              onChange={(event) => {
                setDescription(event.target.value)
              }}
            />
          </div>
          <button type="submit" className="button button--primary" disabled={creating}>
            {creating ? 'Creating…' : 'Create knowledge base'}
          </button>
        </form>
        {createError ? (
          <ErrorState
            error={createError}
            onRetry={
              createError.code === 'CONFLICT'
                ? () => {
                    setCreateError(null)
                  }
                : undefined
            }
          />
        ) : null}
      </div>

      <div className="card">
        <div className="card__header">
          <h2>All knowledge bases</h2>
          <button type="button" className="button button--small" onClick={list.reload}>
            Refresh
          </button>
        </div>

        {actionError ? <ErrorState error={actionError} /> : null}
        {list.loading ? <Loading label="Loading knowledge bases…" /> : null}
        {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : null}

        {!list.loading && !list.error && knowledgeBases.length === 0 ? (
          <EmptyState title="No knowledge bases yet">
            <p>Create one above, then upload PDF, Markdown or text documents to it.</p>
          </EmptyState>
        ) : null}

        {knowledgeBases.length > 0 ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {knowledgeBases.map((knowledgeBase) => (
                  <tr key={knowledgeBase.id}>
                    <td>
                      <Link to={`/knowledge-bases/${knowledgeBase.id}`}>{knowledgeBase.name}</Link>
                      <div className="mono" style={{ color: 'var(--text-muted)' }}>
                        {knowledgeBase.id}
                      </div>
                    </td>
                    <td>{knowledgeBase.description ?? '—'}</td>
                    <td>{formatTimestamp(knowledgeBase.created_at)}</td>
                    <td>
                      <ConfirmButton
                        label="Delete"
                        confirmLabel="Delete it"
                        onConfirm={() => remove(knowledgeBase)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {knowledgeBases.length > 0 ? (
          <p className="card__hint" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
            {formatCount(knowledgeBases.length)} knowledge base
            {knowledgeBases.length === 1 ? '' : 's'}.
          </p>
        ) : null}
      </div>
    </section>
  )
}
