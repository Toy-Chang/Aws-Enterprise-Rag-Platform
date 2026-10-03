/**
 * Test helpers for the Cognito pieces.
 *
 * `configureCognito` stubs the `VITE_` variables *before* the auth modules are imported.
 * That matters: `authEnabled` and `cognitoConfig` are read once at module load, exactly as
 * Vite inlines them at build time, so a test that wants authentication on has to set the
 * environment and then import the module — there is no runtime re-read to poke.
 */

import { vi } from 'vitest'

import type { CognitoConfig } from '../auth/config'
export const TEST_DOMAIN = 'test-tenant.auth.eu-west-1.amazoncognito.com'
export const TEST_CLIENT_ID = 'test-client-id'
export const TEST_REDIRECT_URI = 'https://app.example.test/callback'
export const TEST_LOGOUT_URI = 'https://app.example.test/'

/** Put values into `import.meta.env`. Passing undefined leaves that variable unset. */
export function stubCognitoEnv(values: {
  domain?: string
  clientId?: string
  redirectUri?: string
  logoutUri?: string
  scopes?: string
}): void {
  const set = (key: string, value: string | undefined): void => {
    if (value === undefined) {
      vi.stubEnv(key, '')
    } else {
      vi.stubEnv(key, value)
    }
  }
  set('VITE_COGNITO_DOMAIN', values.domain)
  set('VITE_COGNITO_CLIENT_ID', values.clientId)
  set('VITE_COGNITO_REDIRECT_URI', values.redirectUri)
  set('VITE_COGNITO_LOGOUT_URI', values.logoutUri)
  set('VITE_COGNITO_SCOPES', values.scopes)
}

/** The configuration a test gets when it asks for authentication to be on. */
export function fullCognitoEnv(): void {
  stubCognitoEnv({
    domain: TEST_DOMAIN,
    clientId: TEST_CLIENT_ID,
    redirectUri: TEST_REDIRECT_URI,
    logoutUri: TEST_LOGOUT_URI,
  })
}

/**
 * Stub the environment, then import the auth modules freshly.
 *
 * Call this in `beforeEach`. `vi.resetModules()` is what makes the second half true: the
 * config is read at module load (as Vite inlines it), so a module that was already imported
 * without configuration cannot be talked into having some.
 *
 * Pass `{ allowDisabled: true }` to load the modules with authentication off; `config` is
 * then null, because there is no configuration to require.
 */
export async function loadAuthModules(
  options: { allowDisabled?: boolean } = {},
): Promise<{
  config: CognitoConfig | null
  cognito: typeof import('../auth/cognito')
  source: typeof import('../auth/session-source')
  store: typeof import('../auth/session')
  configModule: typeof import('../auth/config')
}> {
  vi.resetModules()
  const configModule = await import('../auth/config')
  const config = options.allowDisabled ? configModule.cognitoConfig : configModule.requireConfig()
  const [cognito, source, store] = await Promise.all([
    import('../auth/cognito'),
    import('../auth/session-source'),
    import('../auth/session'),
  ])
  return { config, cognito, source, store, configModule }
}

function base64Url(value: string): string {
  return btoa(value).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * A structurally valid JWT. The signature is a fixed string: nothing on the client verifies
 * it, and every test here is about reading claims, not about trusting them.
 */
export function makeJwt(payload: Record<string, unknown>): string {
  return `${base64Url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))}.${base64Url(
    JSON.stringify(payload),
  )}.test-signature`
}

export function accessTokenFor(
  options: { sub?: string; groups?: string[]; expiresInSeconds?: number } = {},
): string {
  return makeJwt({
    sub: options.sub ?? 'user-1',
    token_use: 'access',
    'cognito:groups': options.groups ?? [],
    exp: Math.floor(Date.now() / 1000) + (options.expiresInSeconds ?? 3600),
  })
}

export function idTokenFor(
  options: { username?: string; email?: string; expiresInSeconds?: number } = {},
): string {
  return makeJwt({
    sub: 'user-1',
    token_use: 'id',
    ...(options.username ? { 'cognito:username': options.username } : {}),
    ...(options.email ? { email: options.email } : {}),
    exp: Math.floor(Date.now() / 1000) + (options.expiresInSeconds ?? 3600),
  })
}

/** A stored session, as `sessionStorage` would hold it. */
export function storedSession(overrides: Partial<Record<string, unknown>> = {}): string {
  return JSON.stringify({
    accessToken: accessTokenFor(),
    idToken: idTokenFor({ username: 'ada' }),
    refreshToken: 'refresh-1',
    expiresAt: Date.now() + 3_600_000,
    groups: ['editor'],
    username: 'ada',
    ...overrides,
  })
}

/** A successful Cognito token response. The access token carries `editor`, by default. */
export function tokenResponse(
  options: {
    accessToken?: string
    idToken?: string
    refreshToken?: string
    expiresIn?: number
    groups?: string[]
  } = {},
): Record<string, unknown> {
  return {
    access_token: options.accessToken ?? accessTokenFor({ groups: options.groups ?? ['editor'] }),
    id_token: options.idToken ?? idTokenFor({ username: 'ada' }),
    ...(options.refreshToken === undefined ? {} : { refresh_token: options.refreshToken }),
    expires_in: options.expiresIn ?? 3600,
    token_type: 'Bearer',
  }
}
