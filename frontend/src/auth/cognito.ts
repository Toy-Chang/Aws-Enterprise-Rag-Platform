/**
 * The three calls to Cognito: start the sign-in, exchange the code, refresh, sign out.
 *
 * Everything is `fetch` against the hosted UI's OAuth 2.0 endpoints — `/oauth2/authorize`
 * (a redirect the browser follows) and `/oauth2/token` (a POST the app makes). There is no
 * client secret anywhere: the app client is public and PKCE is what protects the code.
 */

import type { CognitoConfig } from './config'
import { cognitoBaseUrl } from './config'
import type { Session, TokenResponse } from './session'
import { sessionFromTokenResponse } from './session'

/** The endpoints Cognito's hosted UI exposes under the domain. */
export const AUTHORIZE_PATH = '/oauth2/authorize'
export const TOKEN_PATH = '/oauth2/token'
export const LOGOUT_PATH = '/logout'

/** Bumped when `exp` is within this window, so a request never races a token's expiry. */
export const REFRESH_SKEW_MS = 60_000

/**
 * Where the PKCE verifier and `state` wait for the redirect back.
 *
 * `sessionStorage` for the same reason the session lives there — and because the callback
 * is a full page load, so the verifier cannot live in memory. A sign-in attempt is
 * tab-scoped: another tab's authorize URL must not be able to complete this one's code.
 */
const PKCE_STORAGE_KEY = 'aws-rag-platform.pkce'

interface PendingAuthorization {
  readonly state: string
  readonly codeVerifier: string
  /** Where to go after the callback, so a deep link survives the round trip. */
  readonly returnTo: string
}

/** A failure from Cognito itself, kept separate from an API failure. */
export class CognitoError extends Error {
  /** The OAuth error code, when Cognito answered with one (`invalid_grant`, …). */
  readonly code: string
  readonly status: number

  constructor(message: string, options: { code: string; status: number }) {
    super(message)
    this.name = 'CognitoError'
    this.code = options.code
    this.status = options.status
  }
}

/** Build the URL the browser is sent to, with the PKCE challenge and the state. */
export function buildAuthorizeUrl(
  config: CognitoConfig,
  params: {
    redirectUri: string
    state: string
    codeChallenge: string
    codeChallengeMethod?: 'S256'
    /** Pre-fills the email box after a sign-out or an expired session. */
    loginHint?: string | null
  },
): string {
  const url = new URL(`${cognitoBaseUrl(config)}${AUTHORIZE_PATH}`)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('client_id', config.clientId)
  url.searchParams.set('redirect_uri', params.redirectUri)
  url.searchParams.set('scope', config.scopes)
  url.searchParams.set('state', params.state)
  url.searchParams.set('code_challenge', params.codeChallenge)
  url.searchParams.set('code_challenge_method', params.codeChallengeMethod ?? 'S256')
  if (params.loginHint) {
    url.searchParams.set('login_hint', params.loginHint)
  }
  return url.toString()
}

/** Absolute URL of the hosted UI's sign-out, with the client and the allowed return URI. */
export function buildLogoutUrl(
  config: CognitoConfig,
  options: { logoutUri?: string } = {},
): string {
  const url = new URL(`${cognitoBaseUrl(config)}${LOGOUT_PATH}`)
  url.searchParams.set('client_id', config.clientId)
  url.searchParams.set('logout_uri', options.logoutUri ?? config.logoutUri)
  return url.toString()
}

export function storePendingAuthorization(pending: PendingAuthorization): void {
  try {
    sessionStorage.setItem(PKCE_STORAGE_KEY, JSON.stringify(pending))
  } catch {
    // Without somewhere to keep the verifier the callback cannot complete; the login page
    // starts a new attempt, which is the safe failure.
  }
}

export function readPendingAuthorization(): PendingAuthorization | null {
  let raw: string | null
  try {
    raw = sessionStorage.getItem(PKCE_STORAGE_KEY)
  } catch {
    return null
  }
  if (raw === null) {
    return null
  }
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) {
      return null
    }
    const candidate = parsed as Record<string, unknown>
    if (
      typeof candidate.state !== 'string' ||
      typeof candidate.codeVerifier !== 'string' ||
      typeof candidate.returnTo !== 'string'
    ) {
      return null
    }
    return {
      state: candidate.state,
      codeVerifier: candidate.codeVerifier,
      returnTo: candidate.returnTo,
    }
  } catch {
    return null
  }
}

/**
 * Forget the pending authorization.
 *
 * Called as soon as `state` has been checked, whether it matched or not: a failed callback
 * must not leave a usable verifier behind for a retry with a replayed code.
 */
export function clearPendingAuthorization(): void {
  try {
    sessionStorage.removeItem(PKCE_STORAGE_KEY)
  } catch {
    // Nothing to clear.
  }
}

async function postToken(config: CognitoConfig, form: URLSearchParams): Promise<TokenResponse> {
  const tokenUrl = `${cognitoBaseUrl(config)}${TOKEN_PATH}`
  let response: Response
  try {
    response = await fetch(tokenUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    })
  } catch (cause) {
    throw new CognitoError('Could not reach the sign-in service.', {
      code: 'NETWORK_ERROR',
      status: 0,
    })
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    body = undefined
  }

  if (!response.ok) {
    const payload = (typeof body === 'object' && body !== null ? body : {}) as Record<
      string,
      unknown
    >
    const code = typeof payload.error === 'string' ? payload.error : `HTTP_${response.status}`
    const description =
      typeof payload.error_description === 'string' ? payload.error_description : null
    throw new CognitoError(description ?? `Cognito refused the request (${code}).`, {
      code,
      status: response.status,
    })
  }

  if (typeof body !== 'object' || body === null) {
    throw new CognitoError('Cognito answered with a body that is not a token response.', {
      code: 'UNEXPECTED_RESPONSE',
      status: response.status,
    })
  }
  return body as TokenResponse
}

/** Exchange the authorization code (plus the verifier) for tokens. No client secret. */
export async function exchangeCode(
  config: CognitoConfig,
  params: { code: string; codeVerifier: string; redirectUri: string },
): Promise<Session> {
  const form = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: config.clientId,
    code: params.code,
    redirect_uri: params.redirectUri,
    code_verifier: params.codeVerifier,
  })
  const tokens = await postToken(config, form)
  const session = sessionFromTokenResponse(tokens)
  if (!session) {
    throw new CognitoError('Cognito returned no access token.', {
      code: 'MISSING_ACCESS_TOKEN',
      status: 200,
    })
  }
  return session
}

/** Swap a refresh token for a new access token. */
export async function refreshSession(
  config: CognitoConfig,
  session: Session,
): Promise<Session | null> {
  if (!session.refreshToken) {
    return null
  }
  const form = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: config.clientId,
    refresh_token: session.refreshToken,
  })
  const tokens = await postToken(config, form)
  return sessionFromTokenResponse(tokens, {
    previousRefreshToken: session.refreshToken,
  })
}

/** True when the access token is close enough to expiry to refresh it first. */
export function needsRefresh(session: Session, skewMs = REFRESH_SKEW_MS): boolean {
  return Date.now() + skewMs >= session.expiresAt
}
