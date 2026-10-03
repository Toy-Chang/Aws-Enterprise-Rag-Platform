import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { empty, errorEnvelope, json, renderPage, stubApi } from '../../test/api'
import { knowledgeBase } from '../../test/fixtures'
import { KnowledgeBasesPage } from './KnowledgeBasesPage'

const LIST_PATH = '/api/v1/knowledge-bases'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('KnowledgeBasesPage', () => {
  it('lists what exists and says so when nothing does', async () => {
    stubApi([{ url: LIST_PATH, response: () => json([knowledgeBase()]) }])

    renderPage(<KnowledgeBasesPage />)

    expect(await screen.findByRole('link', { name: 'Platform runbooks' })).toBeInTheDocument()
    expect(screen.getByText('kb-1')).toBeInTheDocument()
    expect(screen.getByText('2026-01-01 09:30:00Z')).toBeInTheDocument()

    vi.unstubAllGlobals()
    stubApi([{ url: LIST_PATH, response: () => json([]) }])
    renderPage(<KnowledgeBasesPage />)
    expect(await screen.findByText('No knowledge bases yet')).toBeInTheDocument()
  })

  it('creates a knowledge base and reloads the list', async () => {
    // The list is empty until the create succeeds, so the reload is what makes the new
    // knowledge base appear.
    let created = false
    const { calls } = stubApi([
      { url: LIST_PATH, response: () => json(created ? [knowledgeBase()] : []) },
      {
        method: 'POST',
        url: LIST_PATH,
        response: () => {
          created = true
          return json(knowledgeBase(), 201)
        },
      },
    ])
    const user = userEvent.setup()

    renderPage(<KnowledgeBasesPage />)
    await screen.findByText('No knowledge bases yet')

    await user.type(screen.getByLabelText('Name'), 'Platform runbooks')
    await user.click(screen.getByRole('button', { name: 'Create knowledge base' }))

    expect(await screen.findByRole('link', { name: 'Platform runbooks' })).toBeInTheDocument()
    const post = calls.find((call) => call.method === 'POST')
    // A blank description is sent as null, which is what the backend stores.
    expect(post?.body).toEqual({ name: 'Platform runbooks', description: null })
    expect(calls.filter((call) => call.method === 'GET')).toHaveLength(2)
  })

  it("surfaces a conflict with the backend's own message", async () => {
    stubApi([
      { url: LIST_PATH, response: () => json([]) },
      {
        method: 'POST',
        url: LIST_PATH,
        response: () =>
          errorEnvelope(
            'CONFLICT',
            'A knowledge base named "Platform runbooks" already exists.',
            { name: 'Platform runbooks' },
            409,
          ),
      },
    ])
    const user = userEvent.setup()

    renderPage(<KnowledgeBasesPage />)
    await user.type(screen.getByLabelText('Name'), 'Platform runbooks')
    await user.click(screen.getByRole('button', { name: 'Create knowledge base' }))

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/already exists/)).toBeInTheDocument()
    expect(within(alert).getByText('CONFLICT')).toBeInTheDocument()
  })

  it('deletes only after a second, explicit click', async () => {
    const { calls } = stubApi([
      { url: LIST_PATH, response: () => json([knowledgeBase()]) },
      { method: 'DELETE', url: `${LIST_PATH}/kb-1`, response: () => empty() },
    ])
    const user = userEvent.setup()

    renderPage(<KnowledgeBasesPage />)
    await screen.findByRole('link', { name: 'Platform runbooks' })

    // One click arms the action; nothing is deleted yet.
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('button', { name: 'Delete it' })).toBeInTheDocument()
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(0)

    // The second click is the one that deletes.
    await user.click(screen.getByRole('button', { name: 'Delete it' }))
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
  })

  it('can back out of a delete', async () => {
    const { calls } = stubApi([
      { url: LIST_PATH, response: () => json([knowledgeBase()]) },
    ])
    const user = userEvent.setup()

    renderPage(<KnowledgeBasesPage />)
    await screen.findByRole('link', { name: 'Platform runbooks' })
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('button', { name: 'Delete it' })).not.toBeInTheDocument()
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(0)
  })

  it('reports an unreachable API as a transport failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    renderPage(<KnowledgeBasesPage />)

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('The API could not be reached')).toBeInTheDocument()
    expect(within(alert).getByText('NETWORK_ERROR')).toBeInTheDocument()
  })
})
