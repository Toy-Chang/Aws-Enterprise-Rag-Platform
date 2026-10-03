/**
 * The session: what the tokens are, where they live, and how they are read.
 *
 * Stored in `sessionStorage`, not `localStorage`. A token that survives the tab is a token
 * that survives the user's attention: it is still there tomorrow on a shared machine, and
 * nothing in the UI ever asked for that. `sessionStorage` ends with the tab, so closing the
 * window is a sign-out the user did not have to remember to perform.
 *
 * Nothing in this module ever logs a token. Tokens appear only as return values and as the
 * `Authorization` header the API client builds from them.
 */

/** The Cognito groups the backend accepts, from the lowest to the highest. */
export type Role = 'viewer' | 'editor' | 'admin'

const ROLES: readonly Role[] = ['viewer', 'editor', 'admin']

/**
 * Where the access token's groups live.
 *
 * The *access* token carries `cognito:groups`, not the ID token, and it is the access token
 * the backend validates on every request — so this claim is the one the UI must mirror.
 */
const GROUPS_CLAIM = 'cognito:groups'

const STORAGE_KEY = 'aws-rag-platform.session'

export interface Session {
  readonly accessToken: string
  readonly idToken: string | null
  readonly refreshToken: string | null
  /** Epoch milliseconds, derived from the access token's `exp`. */
  readonly expiresAt: number
  readonly groups: readonly Role[]
  readonly username: string | null
}

/** What Cognito's `/oauth2/token` answers. Fields are optional: the error shape differs. */
export interface TokenResponse {
  access_token?: string
  id_token?: string
  refresh_token?: string
  expires_in?: number
  token_type?: string
  error?: string
  error_description?: string
}

function decodeBase64Url(value: string): string | null {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/')
  const remainder = padded.length % 4
  try {
    return atob(remainder === 0 ? padded : padded + '='.repeat(4 - remainder))
  } catch {
    return null
  }
}

/**
 * The claims of a JWT, without verifying its signature.
 *
 * Deliberately unverified, and deliberately not used for any access decision: the backend
 * verifies the signature on every request, and the worst the UI can do with an unverified
 * claim is show the wrong name or hide a button that would then be refused with a 403.
 * Verification in the browser would need the JWKS and a crypto stack, for no gain.
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split('.')
  if (parts.length !== 3) {
    return null
  }
  const payload = parts[1]
  if (payload === undefined) {
    return null
  }
  const json = decodeBase64Url(payload)
  if (json === null) {
    return null
  }
  try {
    const parsed: unknown = JSON.parse(json)
    if (typeof parsed !== 'object' || parsed === null) {
      return null
    }
    return parsed as Record<string, unknown>
  } catch {
    return null
  }
}

/** Keep only the group names the backend knows; an unknown group grants nothing. */
export function readGroups(token: string): Role[] {
  const payload = decodeJwtPayload(token)
  const raw = payload?.[GROUPS_CLAIM]
  if (!Array.isArray(raw)) {
    return []
  }
  return ROLES.filter((role) => raw.includes(role))
}

/** A display name: Cognito's `username` when present, else the email in the ID token. */
export function readUsername(idToken: string | null): string | null {
  if (!idToken) {
    return null
  }
  const payload = decodeJwtPayload(idToken)
  if (!payload) {
    return null
  }
  for (const claim of ['cognito:username', 'username', 'email']) {
    const value = payload[claim]
    if (typeof value === 'string' && value !== '') {
      return value
    }
  }
  return null
}

/**
 * Turn a token response into a session.
 *
 * `expires_in` is seconds from now; a small skew is subtracted so a token is treated as
 * expired slightly before Cognito would reject it, rather than racing a request against it.
 */
export function sessionFromTokenResponse(
  tokens: TokenResponse,
  options: { previousRefreshToken?: string | null; skewMs?: number } = {},
): Session | null {
  const accessToken = tokens.access_token
  if (typeof accessToken !== 'string' || accessToken === '') {
    return null
  }
  const expiresIn = typeof tokens.expires_in === 'number' ? tokens.expires_in : 0
  const skewMs = options.skewMs ?? 0
  return {
    accessToken,
    idToken: typeof tokens.id_token === 'string' ? tokens.id_token : null,
    // A refresh response does not repeat the refresh token; keep the one already held.
    refreshToken:
      typeof tokens.refresh_token === 'string' ? tokens.refresh_token : (options.previousRefreshToken ?? null),
    expiresAt: Date.now() + expiresIn * 1000 - skewMs,
    groups: readGroups(accessToken),
    username: readUsername(typeof tokens.id_token === 'string' ? tokens.id_token : null),
  }
}

/** True when the access token is past (or within `skewMs` of) its expiry. */
export function isExpired(session: Session, skewMs = 0): boolean {
  return Date.now() + skewMs >= session.expiresAt
}

function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value)
}

/** Parse a stored session, discarding anything that is not exactly the shape expected. */
function parseSession(raw: string): Session | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof parsed !== 'object' || parsed === null) {
    return null
  }
  const candidate = parsed as Record<string, unknown>
  const accessToken = candidate.accessToken
  const expiresAt = candidate.expiresAt
  if (typeof accessToken !== 'string' || typeof expiresAt !== 'number') {
    return null
  }
  const groups = Array.isArray(candidate.groups) ? candidate.groups.filter(isRole) : []
  return {
    accessToken,
    idToken: typeof candidate.idToken === 'string' ? candidate.idToken : null,
    refreshToken: typeof candidate.refreshToken === 'string' ? candidate.refreshToken : null,
    expiresAt,
    groups,
    username: typeof candidate.username === 'string' ? candidate.username : null,
  }
}

/**
 * The one place that touches `sessionStorage` directly.
 *
 * Every method tolerates the storage being unavailable (Safari private mode, a sandboxed
 * iframe): a storage failure must sign the user out, not throw out of a React render.
 */
export const sessionStore = {
  load(): Session | null {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY)
      return raw === null ? null : parseSession(raw)
    } catch {
      return null
    }
  },
  save(session: Session): void {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    } catch {
      // Storage is full or denied; the in-memory session still works for this render.
    }
  },
  clear(): void {
    try {
      sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // Nothing to clear if the storage was never readable.
    }
  },
}

/** The access token's `exp` claim in milliseconds. Null when the token is not a JWT. */
export function accessTokenExpiry(accessToken: string): number | null {
  const payload = decodeJwtPayload(accessToken)
  const exp = payload?.['exp']
  return typeof exp === 'number' ? exp * 1000 : null
}
