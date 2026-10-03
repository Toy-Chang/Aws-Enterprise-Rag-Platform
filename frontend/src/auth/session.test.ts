/**
 * The session: storage, claims, expiry, and the ways it ends.
 *
 * The interesting cases are the failures. A stored session that cannot be parsed, a token
 * that expires while the user is reading the page, a refresh Cognito refuses — each has to
 * end as "signed out", because the alternative is a UI that keeps sending a dead token and
 * showing the resulting `401`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type * as CognitoModule from './cognito'
import type * as ConfigModule from './config'
import type * as SessionModule from './session'
import type * as SourceModule from './session-source'
import {
  accessTokenFor,
  fullCognitoEnv,
  idTokenFor,
  loadAuthModules,
  makeJwt,
  storedSession,
  tokenResponse,
} from '../test/cognito'

const STORAGE_KEY = 'aws-rag-platform.session'
const fetchMock = vi.fn()

let store: typeof SessionModule
let source: typeof SourceModule
let cognito: typeof CognitoModule
let configModule: typeof ConfigModule

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A session value for the pure helpers, which do not need it to be stored. */
function sessionValue(overrides: Partial<SessionModule.Session> = {}): SessionModule.Session {
  return {
    accessToken: 'a',
    idToken: null,
    refreshToken: 'refresh-1',
    expiresAt: Date.now() + 60_000,
    groups: [],
    username: null,
    ...overrides,
  }
}

beforeEach(async () => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  sessionStorage.clear()
  fullCognitoEnv()
  const loaded = await loadAuthModules()
  store = loaded.store
  source = loaded.source
  cognito = loaded.cognito
  configModule = loaded.configModule
})

afterEach(() => {
  source.resetSessionSourceForTests()
  sessionStorage.clear()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('decodeJwtPayload', () => {
  it('reads the claims of a well-formed token', () => {
    expect(store.decodeJwtPayload(makeJwt({ sub: 'u1', 'cognito:groups': ['admin'] }))).toEqual({
      sub: 'u1',
      'cognito:groups': ['admin'],
    })
  })

  it('answers null for anything that is not a JWT', () => {
    expect(store.decodeJwtPayload('not-a-token')).toBeNull()
    expect(store.decodeJwtPayload('a.b')).toBeNull()
    // A payload segment that is not valid base64url, and one that is not JSON.
    expect(store.decodeJwtPayload('a.!!!.c')).toBeNull()
    expect(store.decodeJwtPayload(`a.${btoa('42')}.c`)).toBeNull()
  })
})

describe('readGroups', () => {
  it('keeps only the groups the backend knows', () => {
    const token = accessTokenFor({ groups: ['viewer', 'editor', 'strangers', 'admin'] })
    expect(store.readGroups(token)).toEqual(['viewer', 'editor', 'admin'])
  })

  it('is empty when the claim is absent or the wrong type', () => {
    expect(store.readGroups(accessTokenFor({ groups: [] }))).toEqual([])
    expect(store.readGroups(makeJwt({ 'cognito:groups': 'admin' }))).toEqual([])
    expect(store.readGroups('not-a-jwt')).toEqual([])
  })
})

describe('sessionFromTokenResponse', () => {
  it('derives expiresAt from expires_in', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-03-01T10:00:00Z'))

    const session = store.sessionFromTokenResponse(tokenResponse({ expiresIn: 300 }))

    expect(session?.expiresAt).toBe(Date.parse('2026-03-01T10:05:00Z'))
  })

  it('keeps a refresh token the response did not repeat', () => {
    const session = store.sessionFromTokenResponse(tokenResponse(), {
      previousRefreshToken: 'refresh-from-before',
    })
    expect(session?.refreshToken).toBe('refresh-from-before')
  })

  it('is null without an access token', () => {
    expect(store.sessionFromTokenResponse({ token_type: 'Bearer' })).toBeNull()
  })
})

describe('sessionStore', () => {
  it('round-trips a session and clears it', () => {
    const session = sessionValue({
      accessToken: accessTokenFor({ groups: ['editor'] }),
      idToken: idTokenFor({ username: 'ada' }),
      groups: ['editor'],
      username: 'ada',
    })

    store.sessionStore.save(session)
    expect(store.sessionStore.load()).toEqual(session)

    store.sessionStore.clear()
    expect(store.sessionStore.load()).toBeNull()
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('discards a stored value it cannot parse instead of throwing', () => {
    sessionStorage.setItem(STORAGE_KEY, 'not json at all')
    expect(store.sessionStore.load()).toBeNull()

    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ accessToken: 'a' }))
    expect(store.sessionStore.load()).toBeNull()
  })

  it('uses sessionStorage, not localStorage, so the token dies with the tab', () => {
    store.sessionStore.save(sessionValue())
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
})

describe('isExpired', () => {
  it('honours the skew so a request does not race the expiry', () => {
    expect(store.isExpired(sessionValue())).toBe(false)
    expect(store.isExpired(sessionValue({ expiresAt: Date.now() - 1 }))).toBe(true)
    expect(store.isExpired(sessionValue(), 120_000)).toBe(true)
  })
})

describe('hasRole', () => {
  it('ranks the groups, so a higher role satisfies a lower requirement', () => {
    expect(configModule.hasRole(sessionValue({ groups: ['viewer'] }), 'viewer')).toBe(true)
    expect(configModule.hasRole(sessionValue({ groups: ['viewer'] }), 'editor')).toBe(false)
    expect(configModule.hasRole(sessionValue({ groups: ['editor'] }), 'viewer')).toBe(true)
    expect(configModule.hasRole(sessionValue({ groups: ['admin'] }), 'editor')).toBe(true)
    expect(configModule.hasRole(sessionValue({ groups: [] }), 'viewer')).toBe(false)
    expect(configModule.hasRole(null, 'viewer')).toBe(false)
  })
})

describe('highestRole', () => {
  it('picks the strongest group and reports none when there is none', () => {
    expect(configModule.highestRole(sessionValue({ groups: ['viewer', 'admin'] }))).toBe('admin')
    expect(configModule.highestRole(sessionValue({ groups: ['editor'] }))).toBe('editor')
    expect(configModule.highestRole(sessionValue({ groups: [] }))).toBeNull()
    expect(configModule.highestRole(null)).toBeNull()
  })
})

describe('getValidAccessToken', () => {
  it('returns the stored token while it is valid, without calling Cognito', async () => {
    sessionStorage.setItem(STORAGE_KEY, storedSession())

    await expect(source.getValidAccessToken()).resolves.toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('refreshes an expired token before using it', async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      storedSession({ expiresAt: Date.now() - 1000, accessToken: accessTokenFor() }),
    )
    const fresh = accessTokenFor({ groups: ['viewer'] })
    fetchMock.mockResolvedValue(jsonResponse(tokenResponse({ accessToken: fresh })))

    await expect(source.getValidAccessToken()).resolves.toBe(fresh)

    const form = new URLSearchParams(
      String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body),
    )
    expect(form.get('grant_type')).toBe('refresh_token')
    // The new token is stored, not merely returned.
    expect(store.sessionStore.load()?.accessToken).toBe(fresh)
  })

  it('clears the session when the token is expired and the refresh fails', async () => {
    sessionStorage.setItem(STORAGE_KEY, storedSession({ expiresAt: Date.now() - 1000 }))
    fetchMock.mockResolvedValue(
      jsonResponse({ error: 'invalid_grant', error_description: 'Refresh Token has expired' }, 400),
    )

    await expect(source.getValidAccessToken()).resolves.toBeNull()
    expect(store.sessionStore.load()).toBeNull()
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(source.sessionSnapshot()).toBeNull()
  })

  it('clears the session when the refresh request cannot be made at all', async () => {
    sessionStorage.setItem(STORAGE_KEY, storedSession({ expiresAt: Date.now() - 1000 }))
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(source.getValidAccessToken()).resolves.toBeNull()
    expect(source.sessionSnapshot()).toBeNull()
  })

  it('clears the session when an expired session has no refresh token', async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      storedSession({ expiresAt: Date.now() - 1000, refreshToken: null }),
    )

    await expect(source.getValidAccessToken()).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(source.sessionSnapshot()).toBeNull()
  })

  it('notifies subscribers once the session is cleared', async () => {
    sessionStorage.setItem(STORAGE_KEY, storedSession({ expiresAt: Date.now() - 1000 }))
    fetchMock.mockResolvedValue(jsonResponse({ error: 'invalid_grant' }, 400))
    const listener = vi.fn()
    source.subscribeToSession(listener)

    await source.getValidAccessToken()

    expect(listener).toHaveBeenCalled()
  })

  it('does nothing at all when authentication is off', async () => {
    vi.unstubAllEnvs()
    vi.stubEnv('VITE_COGNITO_DOMAIN', '')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', '')
    const loaded = await loadAuthModules()
    sessionStorage.setItem(STORAGE_KEY, storedSession())

    await expect(loaded.source.getValidAccessToken()).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(loaded.configModule.authEnabled).toBe(false)
  })
})

describe('renewAfterUnauthorized', () => {
  it('exchanges the refresh token and reports the new session', async () => {
    sessionStorage.setItem(STORAGE_KEY, storedSession())
    fetchMock.mockResolvedValue(jsonResponse(tokenResponse({ refreshToken: 'refresh-2' })))

    const renewed = await source.renewAfterUnauthorized()

    expect(renewed?.refreshToken).toBe('refresh-2')
  })

  it('ends the session when Cognito refuses', async () => {
    sessionStorage.setItem(STORAGE_KEY, storedSession())
    fetchMock.mockResolvedValue(jsonResponse({ error: 'invalid_grant' }, 400))

    await expect(source.renewAfterUnauthorized()).resolves.toBeNull()
    expect(source.sessionSnapshot()).toBeNull()
  })

  it('has nothing to renew without a session', async () => {
    await expect(source.renewAfterUnauthorized()).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('refresh skew', () => {
  it('refreshes inside the skew but treats the token as not yet expired', () => {
    const session = sessionValue({ expiresAt: Date.now() + 60_000 })
    expect(cognito.needsRefresh(session)).toBe(true)
    expect(store.isExpired(session)).toBe(false)
  })
})
