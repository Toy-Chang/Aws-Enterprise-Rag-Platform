import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { errorEnvelope, json, renderPage, stubApi } from '../../test/api'
import { answeredQuery, insufficientEvidence } from '../../test/fixtures'
import { QueryPanel } from './QueryPanel'

const QUERY_PATH = '/api/v1/knowledge-bases/kb-1/query'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('QueryPanel', () => {
  it('shows the answer with its citations and the trace of the request', async () => {
    stubApi([{ method: 'POST', url: QUERY_PATH, response: () => json(answeredQuery()) }])
    const user = userEvent.setup()

    renderPage(<QueryPanel knowledgeBaseId="kb-1" />)
    await user.type(screen.getByLabelText('Question'), 'How often do credentials rotate?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))

    // The answer is matched by its citation marker, which the snippet does not carry.
    expect(await screen.findByText(/^\[1\] Credential rotation/)).toBeInTheDocument()
    // The citation carries the document, its heading path, its chunk and its score.
    expect(screen.getByText(/incident-response\.md/)).toBeInTheDocument()
    expect(screen.getByText(/Encryption policy › Credential rotation/)).toBeInTheDocument()
    expect(screen.getByText(/score 0\.369/)).toBeInTheDocument()
    // An extractive answer says so, so nobody reads it as model output.
    expect(screen.getByText(/no model wrote this text/)).toBeInTheDocument()
    expect(screen.getByText(/Tokens: not reported/)).toBeInTheDocument()

    // The trace is present and named, with the request id that ties it to the logs.
    await user.click(screen.getByText('Trace'))
    expect(screen.getByText('req-1')).toBeInTheDocument()
    expect(screen.getByText('extractive-local')).toBeInTheDocument()
  })

  it('reports missing evidence as a result with the counts that explain it', async () => {
    stubApi([{ method: 'POST', url: QUERY_PATH, response: () => json(insufficientEvidence()) }])
    const user = userEvent.setup()

    renderPage(<QueryPanel knowledgeBaseId="kb-1" />)
    await user.type(screen.getByLabelText('Question'), 'What is the holiday schedule?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('Not enough evidence in this knowledge base')).toBeInTheDocument()
    expect(screen.getByText(/3 candidates and 0 cleared the similarity/)).toBeInTheDocument()
    // The generator never ran, so the page says so rather than implying an empty answer.
    expect(screen.getByText(/stage ran for this question/)).toBeInTheDocument()
    // No citation list is rendered for an answer that has none.
    expect(screen.queryByText(/chunk #/)).not.toBeInTheDocument()
  })

  it('sends the retrieval overrides as numbers and only when they are given', async () => {
    const { calls } = stubApi([
      { method: 'POST', url: QUERY_PATH, response: () => json(answeredQuery()) },
    ])
    const user = userEvent.setup()

    renderPage(<QueryPanel knowledgeBaseId="kb-1" />)
    await user.type(screen.getByLabelText('Question'), 'How often?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    await screen.findByText(/^\[1\] Credential rotation/)

    // The question box is cleared after an ask, so a second question is typed again; the
    // overrides stay filled in, which is what makes them worth sending.
    await user.type(screen.getByLabelText('Passages (top-k)'), '3')
    await user.type(screen.getByLabelText('Minimum score'), '0.35')
    await user.type(screen.getByLabelText('Question'), 'How often exactly?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    await screen.findAllByText(/^\[1\] Credential rotation/)

    expect(calls[0]?.body).toEqual({ question: 'How often?' })
    expect(calls[1]?.body).toEqual({
      question: 'How often exactly?',
      top_k: 3,
      min_score: 0.35,
    })
  })

  it('rejects an unusable top-k locally rather than asking the server to reject it', async () => {
    const { calls } = stubApi([
      { method: 'POST', url: QUERY_PATH, response: () => json(answeredQuery()) },
    ])
    const user = userEvent.setup()

    renderPage(<QueryPanel knowledgeBaseId="kb-1" />)
    await user.type(screen.getByLabelText('Question'), 'How often?')
    await user.type(screen.getByLabelText('Passages (top-k)'), '99')
    await user.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('Top-k must be a whole number between 1 and 50.')).toBeInTheDocument()
    expect(calls).toHaveLength(0)

    await user.clear(screen.getByLabelText('Passages (top-k)'))
    await user.type(screen.getByLabelText('Passages (top-k)'), '2.5')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('Top-k must be a whole number between 1 and 50.')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('shows a failed question with the backend code and request id', async () => {
    stubApi([
      {
        method: 'POST',
        url: QUERY_PATH,
        response: () =>
          errorEnvelope('GENERATION_FAILED', 'The model could not be reached.', {}, 502, 'req-9'),
      },
    ])
    const user = userEvent.setup()

    renderPage(<QueryPanel knowledgeBaseId="kb-1" />)
    await user.type(screen.getByLabelText('Question'), 'How often?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/model could not be reached/)).toBeInTheDocument()
    expect(within(alert).getByText('GENERATION_FAILED')).toBeInTheDocument()
    expect(within(alert).getByText('req-9')).toBeInTheDocument()
  })
})
