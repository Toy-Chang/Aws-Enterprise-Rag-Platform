/**
 * The HTTP client: one place that knows how to call the backend and how it fails.
 *
 * Two properties matter for an operator UI and are asserted in the tests:
 *
 * - A failure keeps the backend's own `code`, `message`, `details` and `request_id`, so a
 *   screen can show what the server said instead of "something went wrong". The request id
 *   is what makes a user-visible error findable in the backend logs.
 * - A response that is not the documented envelope is still an error, not a crash. A proxy
 *   returning an HTML error page must not turn into a JSON parse exception.
 *
 * Authentication is attached here and nowhere else. When a session exists the request
 * carries `Authorization: Bearer <access token>`; the token is refreshed *before* it is
 * used if it is close to expiry, and a `401` — the token was revoked, rotated, or otherwise
 * rejected — triggers one refresh-and-retry. If that fails the session is cleared and the
 * user is sent to `/login`, because a page that can only ever return `401` is worse than a
 * sign-in prompt. With authentication off (no Cognito configuration) none of this happens.
 */

import { authEnabled } from '../auth/config'
import {
  getValidAccessToken,
  renewAfterUnauthorized,
  requestSignIn,
} from '../auth/session-source'
import type { ErrorEnvelope } from './types'

/**
 * Where the API lives. Empty by default so requests go to the same origin: the dev server
 * proxies `/api` to the backend, and a deployment serves both from one origin.
 */
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

/** A failed request, whether the server answered with an error or not at all. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(
    message: string,
    options: { status: number; code: string; details?: unknown; requestId?: string | null },
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.details = options.details ?? null
    this.requestId = options.requestId ?? null
  }

  /** True when the request never reached the server, or the answer was not the API's. */
  get isTransportFailure(): boolean {
    return this.status === 0
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

/**
 * Turn anything thrown into an ApiError.
 *
 * A component that renders a failure must not crash because the failure was a plain
 * `Error` rather than the one the client raises.
 */
export function asApiError(value: unknown): ApiError {
  if (value instanceof ApiError) {
    return value
  }
  return new ApiError(value instanceof Error ? value.message : String(value), {
    status: 0,
    code: 'UNEXPECTED_ERROR',
    details: value instanceof Error ? value.stack : undefined,
  })
}

/** A `{ code, message, details, request_id }` body looks like the documented envelope. */
function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const candidate = value as { error?: unknown; request_id?: unknown }
  if (typeof candidate.request_id !== 'string') {
    return false
  }
  if (typeof candidate.error !== 'object' || candidate.error === null) {
    return false
  }
  const error = candidate.error as { code?: unknown; message?: unknown }
  return typeof error.code === 'string' && typeof error.message === 'string'
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (text.length === 0) {
    // No body at all: the delete endpoints answer 204, and callers ask for `void`.
    return undefined
  }
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  /** Sent as JSON. Mutually exclusive with `body`. */
  json?: unknown
  /** Sent as multipart/form-data, so the browser sets the boundary. */
  body?: FormData
  signal?: AbortSignal
}

/**
 * Perform one request and return the parsed body.
 *
 * Resolves to `undefined` for an empty body (the delete endpoints answer `204`), which is
 * why the return type is generic and callers that expect nothing ask for `void`.
 *
 * At most two attempts are made: the first with whatever token is valid now, and — only
 * after a `401` and only when authentication is on — a second after a refresh. The loop
 * cannot run away, and a `403` is *not* retried: the token was accepted, the role was not.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const authorized = authEnabled
  let renewed = false

  for (;;) {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (options.json !== undefined) {
      headers['Content-Type'] = 'application/json'
    }
    if (authorized) {
      // A refresh happens inside this call when the stored token is at or near expiry, so
      // the header below is never built from a token about to be rejected.
      const token = await getValidAccessToken()
      if (token) {
        headers.Authorization = `Bearer ${token}`
      }
    }

    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method: options.method ?? 'GET',
        headers,
        body: options.json !== undefined ? JSON.stringify(options.json) : options.body,
        ...(options.signal ? { signal: options.signal } : {}),
      })
    } catch (cause) {
      // The request never completed: the backend is down, the network dropped, or the
      // caller aborted. An abort is the caller's own doing, so it is re-thrown as-is.
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        throw cause
      }
      throw new ApiError('Could not reach the API.', {
        status: 0,
        code: 'NETWORK_ERROR',
        details: cause instanceof Error ? cause.message : String(cause),
      })
    }

    if (authorized && response.status === 401 && !renewed) {
      renewed = true
      // `renewAfterUnauthorized` clears the session itself when Cognito refuses, so a null
      // answer is already a signed-out state.
      const session = await renewAfterUnauthorized()
      if (session) {
        continue
      }
      requestSignIn()
    }

    const body = await readBody(response)

    if (!response.ok) {
      // A `401` here has already been through the refresh attempt above. Keeping the
      // backend's own `UNAUTHENTICATED` envelope matters: it is the server's explanation,
      // and the sign-in redirect is the client's reaction to it.
      if (isErrorEnvelope(body)) {
        throw new ApiError(body.error.message, {
          status: response.status,
          code: body.error.code,
          details: body.error.details,
          requestId: body.request_id,
        })
      }
      // An error that did not come from the application: a proxy page, a truncated response,
      // a server that crashed before the handler ran.
      throw new ApiError(`The API returned ${response.status} in an unexpected format.`, {
        status: response.status,
        code: 'UNEXPECTED_RESPONSE',
        details: typeof body === 'string' ? body.slice(0, 500) : body,
        requestId: response.headers.get('X-Request-ID'),
      })
    }

    return body as T
  }
}

/** Field-level messages from a FastAPI validation failure, when the details carry them. */
export function validationMessages(error: ApiError): string[] {
  const details = error.details
  if (typeof details !== 'object' || details === null) {
    return []
  }
  const errors = (details as { errors?: unknown }).errors
  if (!Array.isArray(errors)) {
    return []
  }
  return errors.flatMap((entry) => {
    if (typeof entry !== 'object' || entry === null) {
      return []
    }
    const { loc, msg } = entry as { loc?: unknown; msg?: unknown }
    if (typeof msg !== 'string') {
      return []
    }
    const field = Array.isArray(loc) ? loc.filter((part) => part !== 'body').join('.') : ''
    return [field ? `${field}: ${msg}` : msg]
  })
}
