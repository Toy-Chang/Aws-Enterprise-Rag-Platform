import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, request, validationMessages } from './client'

const fetchMock = vi.fn()

function jsonResponse(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
}

function envelope(code: string, message: string, details: unknown = {}) {
  return {
    request_id: 'req-1',
    error: { code, message, details },
  }
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request', () => {
  it('returns the parsed body and asks for JSON, same-origin', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'kb-1', name: 'Runbooks' }))

    const result = await request<{ id: string; name: string }>('/api/v1/knowledge-bases')

    expect(result).toEqual({ id: 'kb-1', name: 'Runbooks' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    // No origin: the dev server proxies, so the browser never makes a cross-origin call.
    expect(url).toBe('/api/v1/knowledge-bases')
    expect((init.headers as Record<string, string>).Accept).toBe('application/json')
    expect(init.method).toBe('GET')
  })

  it('serialises a JSON body and declares its content type', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'kb-1' }, { status: 201 }))

    await request('/api/v1/knowledge-bases', { method: 'POST', json: { name: 'Runbooks' } })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.body).toBe('{"name":"Runbooks"}')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('lets the browser set the multipart boundary for a form body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'doc-1' }, { status: 201 }))
    const body = new FormData()
    body.append('file', new File(['hello'], 'a.md', { type: 'text/markdown' }))

    await request('/api/v1/knowledge-bases/kb-1/documents', { method: 'POST', body })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.body).toBe(body)
    // Setting Content-Type by hand would drop the boundary and break the upload.
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
  })

  it('returns undefined for an empty body, which is what the deletes answer', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))

    await expect(request('/api/v1/knowledge-bases/kb-1', { method: 'DELETE' })).resolves.toBe(
      undefined,
    )
  })

  it("keeps the backend's code, message, details and request id on an error", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(envelope('CONFLICT', 'A knowledge base named "Runbooks" already exists.', {
        name: 'Runbooks',
      }), { status: 409 }),
    )

    const error = await request('/api/v1/knowledge-bases', { method: 'POST', json: {} }).catch(
      (thrown: unknown) => thrown,
    )

    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.status).toBe(409)
    expect(apiError.code).toBe('CONFLICT')
    expect(apiError.message).toContain('already exists')
    expect(apiError.details).toEqual({ name: 'Runbooks' })
    // The request id is what makes this failure findable in the backend logs.
    expect(apiError.requestId).toBe('req-1')
    expect(apiError.isTransportFailure).toBe(false)
  })

  it('reports an error that did not come from the application without crashing', async () => {
    fetchMock.mockResolvedValue(
      new Response('<html>502 Bad Gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html', 'X-Request-ID': 'from-proxy' },
      }),
    )

    const error = (await request('/health').catch((thrown: unknown) => thrown)) as ApiError

    expect(error.code).toBe('UNEXPECTED_RESPONSE')
    expect(error.status).toBe(502)
    expect(error.details).toContain('502 Bad Gateway')
    expect(error.requestId).toBe('from-proxy')
  })

  it('reports a request that never reached the server as a transport failure', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    const error = (await request('/health').catch((thrown: unknown) => thrown)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(0)
    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.isTransportFailure).toBe(true)
    expect(error.details).toBe('Failed to fetch')
  })

  it("lets the caller's own abort through instead of dressing it as a failure", async () => {
    const abort = new DOMException('The operation was aborted.', 'AbortError')
    fetchMock.mockRejectedValue(abort)

    const error = await request('/api/v1/metrics').catch((thrown: unknown) => thrown)

    expect(error).toBe(abort)
    expect(error).not.toBeInstanceOf(ApiError)
  })

  it('passes the abort signal to fetch', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ window: 1024 }))
    const controller = new AbortController()

    await request('/api/v1/metrics', { signal: controller.signal })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.signal).toBe(controller.signal)
  })
})

describe('validationMessages', () => {
  it('turns a FastAPI validation failure into per-field lines', () => {
    const error = new ApiError('Validation failed', {
      status: 422,
      code: 'UNPROCESSABLE_ENTITY',
      details: {
        errors: [
          { loc: ['body', 'name'], msg: 'String should have at most 120 characters' },
          { loc: ['body', 'documents', 0, 'content'], msg: 'String should have at least 1 character' },
          { msg: 'Value error, not a mapping' },
        ],
      },
    })

    expect(validationMessages(error)).toEqual([
      'name: String should have at most 120 characters',
      'documents.0.content: String should have at least 1 character',
      'Value error, not a mapping',
    ])
  })

  it('reports nothing for an error that carries no field details', () => {
    expect(
      validationMessages(new ApiError('Nope', { status: 404, code: 'NOT_FOUND', details: {} })),
    ).toEqual([])
    expect(
      validationMessages(new ApiError('Nope', { status: 0, code: 'NETWORK_ERROR', details: 'x' })),
    ).toEqual([])
  })
})
