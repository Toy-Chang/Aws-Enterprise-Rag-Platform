/**
 * `/login` — start the sign-in, or finish the sign-out.
 *
 * Two entry points share the route because they are the same moment for the user: "I am not
 * signed in and I want the right thing to happen". `?signout=1` is what the header's sign-out
 * control uses, so the control can stay a plain link; the sign-out itself is a redirect to
 * Cognito's `/logout`, which has to be a navigation anyway.
 *
 * With authentication off the page says so instead of redirecting into a domain that was
 * never configured.
 */

import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useAuth } from '../../auth/AuthContext'

/** Only in-app paths are accepted: `returnTo` must not become an open redirect. */
function safeReturnTo(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//')) {
    return '/'
  }
  return value
}

export function LoginPage(): ReactNode {
  const auth = useAuth()
  const [searchParams] = useSearchParams()
  const returnTo = safeReturnTo(searchParams.get('returnTo'))
  const signingOut = searchParams.get('signout') === '1'

  useEffect(() => {
    if (!auth.enabled) {
      return
    }
    if (signingOut) {
      auth.signOut()
      return
    }
    if (auth.session) {
      // Already signed in: there is nothing to ask Cognito for.
      return
    }
    auth.signIn({ returnTo })
    // `signIn` and `signOut` are stable (useCallback) and the two params are the whole
    // input, so this effect runs once per page load and never restarts the redirect.
  }, [auth, returnTo, signingOut])

  if (!auth.enabled) {
    return (
      <section className="card">
        <h1>Authentication is off</h1>
        <p className="card__hint">
          This build has no <code>VITE_COGNITO_DOMAIN</code> or{' '}
          <code>VITE_COGNITO_CLIENT_ID</code>, so the app calls the API without a token. Set
          both (see <code>frontend/.env.example</code>) and rebuild to require a sign-in.
        </p>
        <p>
          <Link className="button" to="/">
            Back to the console
          </Link>
        </p>
      </section>
    )
  }

  return (
    <section className="card" aria-label="Redirecting to sign in">
      <h1>{signingOut ? 'Signing out…' : 'Signing in…'}</h1>
      <p className="card__hint">
        Taking you to the sign-in service. If nothing happens,{' '}
        <a href={`/login?returnTo=${encodeURIComponent(returnTo)}`}>start over</a>.
      </p>
    </section>
  )
}
