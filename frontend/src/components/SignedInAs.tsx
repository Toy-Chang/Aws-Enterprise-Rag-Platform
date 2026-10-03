/**
 * "Signed in as …", and the way out.
 *
 * The role is shown because it is the thing that explains the rest of the page: an editor
 * who cannot find the delete button should be able to see that deletion needs `admin`,
 * rather than wonder whether the button is missing or the page is broken.
 *
 * A real link to `/login` rather than a click handler, for the same reason as the sign-in
 * prompt: the flow ends in a full-page redirect, so it should behave like a navigation.
 */

import type { ReactNode } from 'react'

import { useAuth, useRole } from '../auth/AuthContext'

export function SignedInAs(): ReactNode {
  const auth = useAuth()
  const role = useRole()

  if (!auth.enabled || !auth.session) {
    return null
  }

  return (
    <div className="session" aria-label="Signed in">
      <span className="session__who" title={auth.session.username ?? 'unknown'}>
        Signed in as <strong>{auth.session.username ?? 'unknown'}</strong>
      </span>
      <span className="badge badge--muted">{role ?? 'no role'}</span>
      <a className="button button--small" href="/login?signout=1">
        Sign out
      </a>
    </div>
  )
}
