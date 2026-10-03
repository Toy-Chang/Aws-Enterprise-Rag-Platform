/**
 * The React face of the session.
 *
 * The provider is the only component that knows the whole story: it loads the stored
 * session on mount, hands it to React, exposes sign-in/sign-out, and binds the callbacks
 * that let the plain HTTP client clear the session and ask for a sign-in.
 *
 * The in-memory session is shared with the API client on purpose. Two copies of "am I
 * signed in" is how a UI ends up showing a signed-in header over a page of `401`s.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from 'react'
import type { ReactNode } from 'react'

import {
  CognitoError,
  buildAuthorizeUrl,
  buildLogoutUrl,
  clearPendingAuthorization,
  exchangeCode,
  readPendingAuthorization,
  storePendingAuthorization,
} from './cognito'
import type { Action } from './config'
import {
  authEnabled,
  cognitoConfig,
  hasRole as sessionHasRole,
  highestRole,
  requiredRole,
} from './config'
import { createCodeChallenge, createCodeVerifier, createState } from './pkce'
import type { Role, Session } from './session'
import {
  bindSessionCallbacks,
  clearSession,
  sessionSnapshot,
  setCurrentSession,
  subscribeToSession,
} from './session-source'

export interface AuthContextValue {
  /** False when the build has no Cognito configuration: the app runs unauthenticated. */
  readonly enabled: boolean
  readonly session: Session | null
  /** True while the callback exchange is in flight. */
  readonly pending: boolean
  /** The last failure from the hosted UI, for the callback page to render. */
  readonly error: string | null
  signIn: (options?: { returnTo?: string; loginHint?: string | null }) => void
  signOut: () => void
  /** Complete the authorization code flow and resolve to where to go next. */
  completeSignIn: (code: string, state: string) => Promise<string>
  /** Record a failure Cognito reported on the callback (e.g. `?error=access_denied`). */
  reportError: (message: string) => void
  can: (action: Action) => boolean
  hasRole: (role: Role) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

/** Auth is off: these do nothing, and no component has to branch to say so. */
const DISABLED_AUTH: AuthContextValue = {
  enabled: false,
  session: null,
  pending: false,
  error: null,
  signIn: () => undefined,
  signOut: () => undefined,
  completeSignIn: () => Promise.reject(new Error('Cognito is not configured.')),
  reportError: () => undefined,
  can: () => true,
  hasRole: () => true,
}

/**
 * Start the redirect, unless we are already somewhere a redirect cannot help.
 *
 * Without this check a `401` on `/login` would navigate to `/login` forever.
 */
function redirectToSignIn(returnTo: string): void {
  if (typeof window === 'undefined') {
    return
  }
  const path = window.location.pathname
  if (path === '/login' || path === '/callback') {
    return
  }
  window.location.assign(`/login?returnTo=${encodeURIComponent(returnTo)}`)
}

export function AuthProvider({ children }: { children: ReactNode }): ReactNode {
  // The store is the source of truth, not a second `useState` copy: when the HTTP client
  // clears the session after a `401`, this component re-renders immediately and the route
  // guard swaps the page for the sign-in card.
  const session = useSyncExternalStore(
    subscribeToSession,
    sessionSnapshot,
    () => null,
  )
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The client cannot import React, so the provider pushes the one behaviour it needs into
  // it. The callback is a stable closure, so binding once on mount is enough.
  useEffect(() => {
    return bindSessionCallbacks({
      onSignInRequired: () => {
        redirectToSignIn(`${window.location.pathname}${window.location.search}`)
      },
    })
  }, [])

  /**
   * Start the authorization code flow.
   *
   * Stable across renders (`useCallback`), because the login page runs it from an effect
   * and an identity that changed every render would restart the redirect forever.
   */
  const signIn = useCallback(
    (options: { returnTo?: string; loginHint?: string | null } = {}) => {
      const config = cognitoConfig
      if (!config) {
        return
      }
      const returnTo = options.returnTo ?? '/'
      const state = createState()
      const codeVerifier = createCodeVerifier()
      setError(null)
      // The verifier and the state wait in sessionStorage: the callback arrives after a
      // full page load, so there is no in-memory value left to compare against.
      void createCodeChallenge(codeVerifier).then((codeChallenge) => {
        storePendingAuthorization({ state, codeVerifier, returnTo })
        window.location.assign(
          buildAuthorizeUrl(config, {
            redirectUri: config.redirectUri,
            state,
            codeChallenge,
            loginHint: options.loginHint ?? null,
          }),
        )
      })
    },
    [],
  )

  const signOut = useCallback(() => {
    const config = cognitoConfig
    if (!config) {
      return
    }
    clearSession()
    clearPendingAuthorization()
    // The hosted UI's /logout also ends Cognito's own session cookie, which is what stops
    // the next sign-in from silently completing against the account just left.
    window.location.assign(buildLogoutUrl(config))
  }, [])

  const completeSignIn = useCallback(async (code: string, state: string): Promise<string> => {
    const config = cognitoConfig
    if (!config) {
      throw new Error('Cognito is not configured: there is nothing to complete.')
    }
    setPending(true)
    setError(null)
    const pendingAuthorization = readPendingAuthorization()
    // Consumed before the check, and before any exchange: a callback whose `state` does not
    // match this tab's attempt is stale or forged, and either way the verifier must not
    // survive it.
    clearPendingAuthorization()
    if (!pendingAuthorization) {
      setPending(false)
      throw new Error('No sign-in attempt is in progress in this tab. Start again at /login.')
    }
    if (pendingAuthorization.state !== state) {
      setPending(false)
      throw new Error(
        'The sign-in response did not match this session. Nothing was signed in; start again at /login.',
      )
    }
    try {
      const next = await exchangeCode(config, {
        code,
        codeVerifier: pendingAuthorization.codeVerifier,
        redirectUri: config.redirectUri,
      })
      setCurrentSession(next)
      setPending(false)
      return pendingAuthorization.returnTo
    } catch (thrown) {
      setPending(false)
      setError(thrown instanceof Error ? thrown.message : String(thrown))
      throw thrown
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      enabled: authEnabled,
      session,
      pending,
      error,
      can: (action) => (authEnabled ? sessionHasRole(session, requiredRole(action)) : true),
      hasRole: (role) => (authEnabled ? sessionHasRole(session, role) : true),
      reportError: (message) => {
        setError(message)
      },
      signIn,
      signOut,
      completeSignIn,
    }),
    [session, pending, error, signIn, signOut, completeSignIn],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/** Read the session. Outside a provider this is the safe, auth-off answer. */
export function useAuth(): AuthContextValue {
  return useContext(AuthContext) ?? DISABLED_AUTH
}

/** The signed-in username, or null. */
export function useUsername(): string | null {
  return useAuth().session?.username ?? null
}

/** The highest role the session holds, for display. */
export function useRole(): Role | null {
  return highestRole(useAuth().session)
}

/** True when the session may perform `action`. Always true when auth is off. */
export function useCan(action: Action): boolean {
  return useAuth().can(action)
}

export { CognitoError }
