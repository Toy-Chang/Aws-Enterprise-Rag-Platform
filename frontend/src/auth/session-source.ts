/**
 * The one in-memory copy of the session, shared by React and the HTTP client.
 *
 * This exists because of a shape problem: the API client is a plain module that knows
 * nothing about React, and React is what owns the session. Rather than teaching the client
 * about hooks, or threading a token through every `api.*` call, the client asks this module
 * for a token and this module is a subscribable store — so when the client clears the
 * session after a `401`, React re-renders in the same tick and the route guard replaces the
 * broken page with the sign-in card instead of letting the next request repeat the failure.
 *
 * The rules are deliberately blunt:
 *
 * - A token is refreshed **before** it is used, once it is inside the refresh skew, so a
 *   request never races an expiry.
 * - A failed refresh is a sign-out, not an error to render: a refresh token that Cognito
 *   refuses is a session that is over.
 * - `401` from the API means the token was rejected anyway (revoked, wrong audience,
 *   rotated keys). The session is cleared and the user is sent to `/login` rather than
 *   being shown a page that can only ever fail.
 */

import { refreshSession } from './cognito'
import { authEnabled, requireConfig } from './config'
import type { Session } from './session'
import { sessionStore } from './session'

let current: Session | null = null
let hydrated = false
const listeners = new Set<() => void>()

/**
 * The callbacks the provider binds so this module never imports React and never navigates
 * on its own: clearing a `401` session is this module's job, sending the user to `/login`
 * is the router's, and tests can bind one without the other.
 */
let onSignInRequired: (() => void) | null = null

function emit(): void {
  for (const listener of listeners) {
    listener()
  }
}

/** Subscribe to session changes. Returns the unsubscribe function React expects. */
export function subscribeToSession(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * The current session, read once from `sessionStorage` on first use.
 *
 * The first read is lazy so the very first render already has an answer — a request fired
 * from a page that mounts before the provider would otherwise go out unauthenticated and
 * be bounced to `/login` for nothing.
 */
export function sessionSnapshot(): Session | null {
  if (!hydrated) {
    hydrated = true
    current = sessionStore.load()
  }
  return current
}

/** Re-read `sessionStorage`. Only needed if something outside the app wrote to it. */
export function rehydrateSession(): Session | null {
  hydrated = true
  current = sessionStore.load()
  emit()
  return current
}

/** Put a session into the store, persisting it unless told otherwise. */
export function setCurrentSession(
  session: Session | null,
  options: { persist?: boolean } = {},
): void {
  hydrated = true
  current = session
  if (options.persist !== false) {
    if (session) {
      sessionStore.save(session)
    } else {
      sessionStore.clear()
    }
  }
  emit()
}

/** Forget the session everywhere, and let React re-render without it. */
export function clearSession(): void {
  if (current === null) {
    sessionStore.clear()
    return
  }
  setCurrentSession(null)
}

/**
 * A token that is valid *now*, refreshing first if it is about to expire.
 *
 * Resolves to null when there is no session, no refresh token, or Cognito refused the
 * refresh. A null here is a signed-out user, never a thrown error: callers attach no header
 * and the API answers `401`, which the client turns into the sign-in prompt.
 */
export async function getValidAccessToken(): Promise<string | null> {
  if (!authEnabled) {
    return null
  }
  const session = sessionSnapshot()
  if (!session) {
    return null
  }
  if (Date.now() < session.expiresAt) {
    return session.accessToken
  }
  const renewed = await renew(session)
  return renewed?.accessToken ?? null
}

/**
 * Retry the refresh once, at the moment a request has already failed with `401`.
 *
 * This path does not care *why* the token was rejected — only whether Cognito will issue a
 * new one. A no-op refresh token, or a refusal, ends the session.
 */
export async function renewAfterUnauthorized(): Promise<Session | null> {
  if (!authEnabled) {
    return null
  }
  const session = sessionSnapshot()
  if (!session) {
    return null
  }
  return await renew(session)
}

async function renew(session: Session): Promise<Session | null> {
  if (!session.refreshToken) {
    clearSession()
    return null
  }
  try {
    const refreshed = await refreshSession(requireConfig(), session)
    if (!refreshed) {
      clearSession()
      return null
    }
    setCurrentSession(refreshed)
    return refreshed
  } catch {
    // A refused refresh token means the session is over; a network blip must not leave an
    // expired token in play either. Both end the same way: signed out.
    clearSession()
    return null
  }
}

/** True when a request should carry a bearer token at all. */
export function shouldAttachToken(): boolean {
  return authEnabled && sessionSnapshot() !== null
}

export function bindSessionCallbacks(callbacks: { onSignInRequired: () => void }): () => void {
  onSignInRequired = callbacks.onSignInRequired
  return () => {
    onSignInRequired = null
  }
}

/** Ask the app to send the user to `/login`. A no-op when nothing is bound. */
export function requestSignIn(): void {
  if (onSignInRequired) {
    onSignInRequired()
  }
}

/** Forget everything this module holds. Test-only: the app never needs a cold cache. */
export function resetSessionSourceForTests(): void {
  current = null
  hydrated = false
  onSignInRequired = null
  listeners.clear()
}
