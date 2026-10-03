import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { errorEnvelope, json, renderRoute, stubApi } from '../../test/api'
import { documentMetadata, knowledgeBase } from '../../test/fixtures'
import { KnowledgeBasePage } from './KnowledgeBasePage'

const KB_PATH = '/api/v1/knowledge-bases/kb-1'
const DOCS_PATH = '/api/v1/knowledge-bases/kb-1/documents'

function renderDetail() {
  return renderRoute('/knowledge-bases/kb-1', 'knowledge-bases/:knowledgeBaseId', (
    <KnowledgeBasePage />
  ))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('KnowledgeBasePage', () => {
  it('opens on the documents tab when the knowledge base is empty', async () => {
    stubApi([
      { url: KB_PATH, response: () => json(knowledgeBase()) },
      { url: DOCS_PATH, response: () => json([]) },
    ])

    renderDetail()

    expect(await screen.findByRole('heading', { name: 'Platform runbooks' })).toBeInTheDocument()
    expect(await screen.findByText('No documents yet')).toBeInTheDocument()
  })

  it('opens on the question box once there is something to ask about', async () => {
    stubApi([
      { url: KB_PATH, response: () => json(knowledgeBase()) },
      { url: DOCS_PATH, response: () => json([documentMetadata()]) },
    ])

    renderDetail()

    expect(await screen.findByRole('heading', { name: 'Ask a question' })).toBeInTheDocument()
    expect(screen.queryByText('No documents yet')).not.toBeInTheDocument()
  })

  it('uploads a file as multipart form data and reloads the list', async () => {
    const { calls } = stubApi([
      { url: KB_PATH, response: () => json(knowledgeBase()) },
      { url: DOCS_PATH, response: () => json([]) },
      { method: 'POST', url: DOCS_PATH, response: () => json(documentMetadata(), 201) },
    ])
    const user = userEvent.setup()

    renderDetail()
    await screen.findByText('No documents yet')

    const file = new File(['# Incident response'], 'incident-response.md', {
      type: 'text/markdown',
    })
    await user.upload(screen.getByLabelText('File'), file)
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    const upload = calls.find((call) => call.method === 'POST')
    expect(upload?.body).toBeInstanceOf(FormData)
    // The field name is `file`, which is what the endpoint declares.
    const sent = (upload?.body as FormData).get('file')
    expect(sent).toBeInstanceOf(File)
    expect((sent as File).name).toBe('incident-response.md')
    expect(calls.filter((call) => call.url === DOCS_PATH && call.method === 'GET')).toHaveLength(2)
  })

  it('shows the failure a document failed with, and offers to reprocess it', async () => {
    const { calls } = stubApi([
      { url: KB_PATH, response: () => json(knowledgeBase()) },
      {
        url: DOCS_PATH,
        response: () =>
          json([
            documentMetadata({
              status: 'failed',
              chunk_count: 0,
              error_message: 'no text could be extracted',
            }),
          ]),
      },
      { method: 'POST', url: `${DOCS_PATH}/doc-1/reprocess`, response: () => json(documentMetadata()) },
    ])
    const user = userEvent.setup()

    renderDetail()
    await screen.findByRole('tab', { name: /Documents/ })
    await user.click(screen.getByRole('tab', { name: /Documents/ }))

    const row = await screen.findByRole('row', { name: /incident-response\.md/ })
    expect(within(row).getByText('failed')).toBeInTheDocument()
    expect(within(row).getByText('no text could be extracted')).toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: 'Reprocess' }))
    expect(calls.some((call) => call.url.endsWith('/reprocess'))).toBe(true)
  })

  it('lists the indexed passages with the structure they came from', async () => {
    stubApi([
      { url: KB_PATH, response: () => json(knowledgeBase()) },
      { url: DOCS_PATH, response: () => json([documentMetadata()]) },
      {
        url: `${DOCS_PATH}/doc-1/chunks`,
        response: () =>
          json([
            {
              id: 'chunk-1',
              document_id: 'doc-1',
              chunk_index: 0,
              content: 'Database credentials rotate every ninety days.',
              char_start: 0,
              char_end: 45,
              page_number: null,
              heading_path: ['Encryption policy', 'Credential rotation'],
              created_at: '2026-01-01T09:31:02Z',
            },
            {
              id: 'chunk-2',
              document_id: 'doc-1',
              chunk_index: 1,
              content: 'Snapshots are retained for thirty-five days.',
              char_start: 46,
              char_end: 92,
              page_number: 3,
              heading_path: [],
              created_at: '2026-01-01T09:31:02Z',
            },
          ]),
      },
    ])
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('tab', { name: /Documents/ }))
    await user.click(await screen.findByRole('button', { name: 'Passages' }))

    expect(await screen.findByText('#0 · Encryption policy › Credential rotation')).toBeInTheDocument()
    expect(screen.getByText('Database credentials rotate every ninety days.')).toBeInTheDocument()
    // A passage with no heading and a page number says so rather than showing an empty path.
    expect(screen.getByText('#1 · no heading · page 3')).toBeInTheDocument()

    // Closing the panel is local: it asks the API for nothing.
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByText('Indexed passages')).not.toBeInTheDocument()
  })

  it('reports a document delete failure without removing the row', async () => {
    stubApi([
      { url: KB_PATH, response: () => json(knowledgeBase()) },
      { url: DOCS_PATH, response: () => json([documentMetadata()]) },
      {
        method: 'DELETE',
        url: `${DOCS_PATH}/doc-1`,
        response: () => errorEnvelope('NOT_FOUND', 'Document not found.', {}, 404),
      },
    ])
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('tab', { name: /Documents/ }))
    await screen.findByRole('row', { name: /incident-response\.md/ })

    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await user.click(screen.getByRole('button', { name: 'Delete it' }))

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('NOT_FOUND')).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /incident-response\.md/ })).toBeInTheDocument()
  })

  it('refreshes the list while a document is still being ingested', async () => {
    let documentCalls = 0
    stubApi([
      { url: KB_PATH, response: () => json(knowledgeBase()) },
      {
        url: DOCS_PATH,
        response: () => {
          documentCalls += 1
          // Pending on the first read, ready afterwards: the page must notice the change
          // without the operator reloading anything.
          return json([documentMetadata({ status: documentCalls === 1 ? 'pending' : 'ready' })])
        },
      },
    ])

    vi.useFakeTimers()
    renderDetail()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(documentCalls).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600)
    })
    expect(documentCalls).toBe(2)

    // Nothing is in flight any more, so the polling stops instead of running forever.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(documentCalls).toBe(2)
  })
})
