/**
 * The Cognito calls: the authorize URL, the code exchange, the refresh, and the logout.
 *
 * These are the places where a mistake is invisible until a real deployment fails, so the
 * assertions are about the exact query parameters and form fields Cognito requires.
 *
 * The modules are imported inside `beforeEach`, after the `VITE_` stubs, because the
 * configuration is read once at module load — the same way Vite inlines it at build time.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type * as CognitoModule from './cognito'
import type * as ConfigModule from './config'
import type * as SourceModule from './session-source'
import type { Session } from './session'
import {
  TEST_CLIENT_ID,
  TEST_DOMAIN,
  TEST_LOGOUT_URI,
  TEST_REDIRECT_URI,
  accessTokenFor,
  fullCognitoEnv,
  idTokenFor,
  loadAuthModules,
  tokenResponse,
} from '../test/cognito'

const fetchMock = vi.fn()

let cognito: typeof CognitoModule
let source: typeof SourceModule
let config: ConfigModule.CognitoConfig

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function urlFrom(input: unknown): URL {
  return new URL(String(input))
}

function formFrom(init: RequestInit | undefined): URLSearchParams {
  return new URLSearchParams(String(init?.body))
}

beforeEach(async () => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  fullCognitoEnv()
  const loaded = await loadAuthModules()
  cognito = loaded.cognito
  source = loaded.source
  config = loaded.config
})

afterEach(() => {
  source.resetSessionSourceForTests()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('buildAuthorizeUrl', () => {
  it('carries state, code_challenge and S256 against the hosted UI domain', () => {
    const url = urlFrom(
      cognito.buildAuthorizeUrl(config, {
        redirectUri: TEST_REDIRECT_URI,
        state: 'the-state',
        codeChallenge: 'the-challenge',
      }),
    )

    expect(url.protocol).toBe('https:')
    expect(url.host).toBe(TEST_DOMAIN)
    expect(url.pathname).toBe('/oauth2/authorize')
    expect(url.searchParams.get('response_type')).toBe('code')
    expect(url.searchParams.get('client_id')).toBe(TEST_CLIENT_ID)
    expect(url.searchParams.get('redirect_uri')).toBe(TEST_REDIRECT_URI)
    expect(url.searchParams.get('scope')).toBe('openid email profile')
    expect(url.searchParams.get('state')).toBe('the-state')
    expect(url.searchParams.get('code_challenge')).toBe('the-challenge')
    expect(url.searchParams.get('code_challenge_method')).toBe('S256')
  })

  it('only adds login_hint when there is one', () => {
    const without = urlFrom(
      cognito.buildAuthorizeUrl(config, {
        redirectUri: TEST_REDIRECT_URI,
        state: 's',
        codeChallenge: 'c',
      }),
    )
    expect(without.searchParams.has('login_hint')).toBe(false)

    const withHint = urlFrom(
      cognito.buildAuthorizeUrl(config, {
        redirectUri: TEST_REDIRECT_URI,
        state: 's',
        codeChallenge: 'c',
        loginHint: 'ada@example.test',
      }),
    )
    expect(withHint.searchParams.get('login_hint')).toBe('ada@example.test')
  })
})

describe('buildLogoutUrl', () => {
  it('names the client and the allowed return URI', () => {
    const url = urlFrom(cognito.buildLogoutUrl(config))
    expect(url.origin).toBe(`https://${TEST_DOMAIN}`)
    expect(url.pathname).toBe('/logout')
    expect(url.searchParams.get('client_id')).toBe(TEST_CLIENT_ID)
    expect(url.searchParams.get('logout_uri')).toBe(TEST_LOGOUT_URI)
  })
})

describe('exchangeCode', () => {
  it('posts authorization_code with the verifier and no client secret', async () => {
    fetchMock.mockResolvedValue(jsonResponse(tokenResponse({ refreshToken: 'refresh-1' })))

    const session = await cognito.exchangeCode(config, {
      code: 'auth-code',
      codeVerifier: 'the-verifier',
      redirectUri: TEST_REDIRECT_URI,
    })

    const [input, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const url = urlFrom(input)
    expect(url.origin).toBe(`https://${TEST_DOMAIN}`)
    expect(url.pathname).toBe('/oauth2/token')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe(
      'application/x-www-form-urlencoded',
    )

    const form = formFrom(init)
    expect(form.get('grant_type')).toBe('authorization_code')
    expect(form.get('client_id')).toBe(TEST_CLIENT_ID)
    expect(form.get('code')).toBe('auth-code')
    expect(form.get('redirect_uri')).toBe(TEST_REDIRECT_URI)
    expect(form.get('code_verifier')).toBe('the-verifier')
    // A public client: a secret here would mean shipping the secret in the bundle.
    expect(form.has('client_secret')).toBe(false)

    expect(session.accessToken).toBeTruthy()
    expect(session.refreshToken).toBe('refresh-1')
    expect(session.username).toBe('ada')
    expect(session.groups).toEqual(['editor'])
    expect(session.expiresAt).toBeGreaterThan(Date.now())
  })

  it("surfaces Cognito's own error code and description", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: 'invalid_grant', error_description: 'Invalid code provided.' },
        400,
      ),
    )

    const error = await cognito
      .exchangeCode(config, {
        code: 'used-code',
        codeVerifier: 'the-verifier',
        redirectUri: TEST_REDIRECT_URI,
      })
      .catch((thrown: unknown) => thrown)

    expect(error).toBeInstanceOf(Error)
    const cognitoError = error as { code: string; message: string; status: number }
    expect(cognitoError.code).toBe('invalid_grant')
    expect(cognitoError.message).toBe('Invalid code provided.')
    expect(cognitoError.status).toBe(400)
  })

  it('refuses a 200 that carries no access token', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ token_type: 'Bearer' }))

    await expect(
      cognito.exchangeCode(config, {
        code: 'auth-code',
        codeVerifier: 'the-verifier',
        redirectUri: TEST_REDIRECT_URI,
      }),
    ).rejects.toThrow(/no access token/i)
  })
})

describe('refreshSession', () => {
  const expiredSession: Session = {
    accessToken: accessTokenFor({ expiresInSeconds: -60 }),
    idToken: idTokenFor({ username: 'ada' }),
    refreshToken: 'refresh-1',
    expiresAt: Date.now() - 60_000,
    groups: ['editor'],
    username: 'ada',
  }

  it('posts refresh_token and keeps the refresh token Cognito does not repeat', async () => {
    fetchMock.mockResolvedValue(jsonResponse(tokenResponse()))

    const refreshed = await cognito.refreshSession(config, expiredSession)

    const form = formFrom((fetchMock.mock.calls[0] as [string, RequestInit])[1])
    expect(form.get('grant_type')).toBe('refresh_token')
    expect(form.get('client_id')).toBe(TEST_CLIENT_ID)
    expect(form.get('refresh_token')).toBe('refresh-1')
    expect(form.has('client_secret')).toBe(false)

    expect(refreshed?.refreshToken).toBe('refresh-1')
    expect(refreshed?.expiresAt).toBeGreaterThan(Date.now())
  })

  it('is a no-op without a refresh token, rather than a doomed request', async () => {
    await expect(
      cognito.refreshSession(config, { ...expiredSession, refreshToken: null }),
    ).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('needsRefresh', () => {
  it('is true inside the skew and false well before it', () => {
    const base: Session = {
      accessToken: 'a',
      idToken: null,
      refreshToken: 'r',
      expiresAt: Date.now() + 10 * 60_000,
      groups: [],
      username: null,
    }
    expect(cognito.needsRefresh(base)).toBe(false)
    expect(cognito.needsRefresh({ ...base, expiresAt: Date.now() + 30_000 })).toBe(true)
    expect(cognito.needsRefresh({ ...base, expiresAt: Date.now() - 1 })).toBe(true)
  })
})

describe('pending authorization', () => {
  it('round-trips through sessionStorage and is cleared on demand', () => {
    cognito.storePendingAuthorization({ state: 's', codeVerifier: 'v', returnTo: '/metrics?x=1' })
    expect(cognito.readPendingAuthorization()).toEqual({
      state: 's',
      codeVerifier: 'v',
      returnTo: '/metrics?x=1',
    })

    cognito.clearPendingAuthorization()
    expect(cognito.readPendingAuthorization()).toBeNull()
  })

  it('ignores a stored value that is not the shape it wrote', () => {
    sessionStorage.setItem('aws-rag-platform.pkce', '{"state":"s"}')
    expect(cognito.readPendingAuthorization()).toBeNull()
  })
})
