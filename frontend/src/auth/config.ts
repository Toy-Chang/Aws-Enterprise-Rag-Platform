/**
 * The Cognito configuration, and the one branch that decides whether authentication exists
 * at all.
 *
 * Authentication is **off** unless both the domain and the client id are set. That is not a
 * fallback for a broken build: the local stack and the screenshot runs have no Cognito to
 * point at, and a UI that redirects to a domain it was never given is not a UI anyone can
 * use. When it is off there is no redirect, no bearer header, and no guard — the app does
 * exactly what it did before Cognito was wired in. Every call site asks `authEnabled`
 * rather than assuming a session exists.
 *
 * The values are public. A `VITE_` variable is compiled into the bundle, which is why the
 * flow is authorization code + PKCE against a *public* app client: there is no secret to
 * leak because there is no secret.
 */

import type { Role, Session } from './session'

export interface CognitoConfig {
  /** Host of the hosted UI, e.g. `my-app.auth.eu-west-1.amazoncognito.com`. No scheme. */
  readonly domain: string
  readonly clientId: string
  readonly redirectUri: string
  readonly logoutUri: string
  readonly scopes: string
}

/**
 * The roles the backend knows, from the lowest to the highest.
 *
 * The backend answers `403 FORBIDDEN` when the caller's group is too low; the UI mirrors
 * that ordering so it can hide an action the server would only refuse. The server remains
 * the authority — this only avoids offering a button that cannot work.
 */
export const ROLE_ORDER: readonly Role[] = ['viewer', 'editor', 'admin']

/** An action that needs a role. The backend is the one that decides; this mirrors it. */
export type Action =
  | 'knowledge-base:create'
  | 'knowledge-base:delete'
  | 'document:upload'
  | 'document:delete'
  | 'document:reprocess'

const ACTION_ROLE: Record<Action, Role> = {
  'knowledge-base:create': 'editor',
  'knowledge-base:delete': 'admin',
  'document:upload': 'editor',
  'document:delete': 'editor',
  'document:reprocess': 'editor',
}

/** The role an action requires, so the UI can say what is missing rather than just hide. */
export function requiredRole(action: Action): Role {
  return ACTION_ROLE[action]
}

/** `window.location.origin + path`, used for the two URLs Cognito must be told about. */
function originUrl(path: string): string {
  if (typeof window === 'undefined') {
    return path
  }
  return `${window.location.origin}${path}`
}

function readEnv(key: keyof ImportMetaEnv): string {
  const value = import.meta.env[key]
  return typeof value === 'string' ? value.trim() : ''
}

/** The configuration, or null when the domain or the client id is absent (auth is off). */
export function resolveConfig(): CognitoConfig | null {
  const domain = readEnv('VITE_COGNITO_DOMAIN')
  const clientId = readEnv('VITE_COGNITO_CLIENT_ID')
  if (domain === '' || clientId === '') {
    return null
  }
  return {
    domain,
    clientId,
    redirectUri: readEnv('VITE_COGNITO_REDIRECT_URI') || originUrl('/callback'),
    logoutUri: readEnv('VITE_COGNITO_LOGOUT_URI') || originUrl('/'),
    scopes: readEnv('VITE_COGNITO_SCOPES') || 'openid email profile',
  }
}

/**
 * Read once at module load.
 *
 * `import.meta.env` is inlined at build time and never changes while the bundle runs, so
 * re-reading it per request would only add a function call to the hot path.
 */
export const cognitoConfig: CognitoConfig | null = resolveConfig()

/** False when the deployment did not configure Cognito: the app runs unauthenticated. */
export const authEnabled: boolean = cognitoConfig !== null

/** The configuration, for callers that only run when `authEnabled` is true. */
export function requireConfig(): CognitoConfig {
  if (!cognitoConfig) {
    throw new Error(
      'Cognito is not configured: set VITE_COGNITO_DOMAIN and VITE_COGNITO_CLIENT_ID, ' +
        'or leave authentication off and never call this.',
    )
  }
  return cognitoConfig
}

/** The hosted UI origin, with the scheme Cognito URLs need. */
export function cognitoBaseUrl(config: CognitoConfig): string {
  return `https://${config.domain}`
}

/** True when the session holds this role or a higher one. */
export function hasRole(session: Session | null, role: Role): boolean {
  if (!session) {
    return false
  }
  const rank = ROLE_ORDER.indexOf(role)
  return session.groups.some((group) => ROLE_ORDER.indexOf(group) >= rank)
}

/** The highest role held, for display. Null when the user is in no known group. */
export function highestRole(session: Session | null): Role | null {
  if (!session) {
    return null
  }
  let best: Role | null = null
  for (const group of session.groups) {
    if (best === null || ROLE_ORDER.indexOf(group) > ROLE_ORDER.indexOf(best)) {
      best = group
    }
  }
  return best
}
