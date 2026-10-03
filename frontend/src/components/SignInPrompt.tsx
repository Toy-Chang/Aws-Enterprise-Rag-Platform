/**
 * What an unauthenticated visitor sees instead of a screen full of `401`s.
 *
 * The sign-in link is a real link, not a click handler: the flow is a full-page redirect to
 * Cognito, so it works with the keyboard, with a middle click, and with the back button,
 * and nothing has to be generated until the click actually happens.
 */

import type { ReactNode } from 'react'

import { useAuth } from '../auth/AuthContext'

function loginHref(returnTo: string): string {
  return `/login?returnTo=${encodeURIComponent(returnTo)}`
}

export function SignInPrompt({
  returnTo,
  message,
}: {
  returnTo: string
  message: string
}): ReactNode {
  const auth = useAuth()

  if (!auth.enabled) {
    // No configuration: there is nothing to sign in to, so there is nothing to say.
    return null
  }

  return (
    <section className="card" aria-label="Sign in required">
      <h1>Sign in</h1>
      <p className="card__hint">{message}</p>
      {auth.error ? (
        <div className="state state--error" role="alert">
          <p className="state__title">Sign-in failed</p>
          <p className="state__body">{auth.error}</p>
        </div>
      ) : null}
      <p>
        <a className="button button--primary" href={loginHref(returnTo)}>
          Sign in with Cognito
        </a>
      </p>
    </section>
  )
}
