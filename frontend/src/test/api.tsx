/**
 * Test helpers: a stubbed API and a router to render a page in.
 *
 * `stubApi` answers by URL and method and returns the documented error envelope for anything
 * unmatched, so a test that forgets a stub fails with the same shape a real 404 would have
 * instead of a `TypeError` from `undefined`.
 */

import { vi } from 'vitest'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function empty(status = 204): Response {
  return new Response(null, { status })
}

export function errorEnvelope(
  code: string,
  message: string,
  details: unknown = {},
  status = 400,
  requestId = 'req-stub',
): Response {
  return json({ request_id: requestId, error: { code, message, details } }, status)
}

export interface RouteStub {
  method?: string
  url: string | RegExp
  response: () => Response | Promise<Response>
}

export interface ApiCall {
  url: string
  method: string
  body: unknown
}

/** Stub `fetch`, recording every call so a test can assert what was sent. */
export function stubApi(routes: RouteStub[]): { calls: ApiCall[] } {
  const calls: ApiCall[] = []
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const rawBody = init?.body
    calls.push({
      url,
      method,
      body:
        typeof rawBody === 'string'
          ? (JSON.parse(rawBody) as unknown)
          : rawBody instanceof FormData
            ? rawBody
            : null,
    })
    for (const route of routes) {
      const matches =
        typeof route.url === 'string' ? route.url === url : route.url.test(url)
      if (matches && (route.method ?? 'GET') === method) {
        return await route.response()
      }
    }
    return errorEnvelope(
      'NOT_FOUND',
      `No stub for ${method} ${url}`,
      {},
      404,
    )
  })
  vi.stubGlobal('fetch', mock)
  return { calls }
}

export function renderPage(ui: ReactElement): RenderResult {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

/** Render one element as the match for a route pattern, so `useParams` works. */
export function renderRoute(
  initialEntry: string,
  pattern: string,
  element: ReactElement,
): RenderResult {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path={pattern} element={element} />
      </Routes>
    </MemoryRouter>,
  )
}
