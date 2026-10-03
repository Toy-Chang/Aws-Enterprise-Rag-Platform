/**
 * `/callback` — where Cognito returns the authorization code.
 *
 * This page is the only place the code is exchanged, and it runs exactly once per page load
 * (a ref guards against React's development double-effect, which would otherwise burn the
 * code on the first pass and fail the second with `invalid_grant`).
 *
 * The failure mode is deliberate: nothing is rendered as success until the exchange has
 * actually completed, and `state` is checked before the code is sent anywhere. A mismatch
 * throws out of `completeSignIn`, the provider records the message, and the guard shows the
 * sign-in prompt with the reason — the user is never quietly signed into the wrong session.
 */

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { useAuth } from '../../auth/AuthContext'
import { Loading } from '../../components/states'

export function CallbackPage(): ReactNode {
  const auth = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [failure, setFailure] = useState<string | null>(null)
  const started = useRef(false)

  const code = searchParams.get('code')
  const state = searchParams.get('state')
  const reportedError = searchParams.get('error')
  const errorDescription = searchParams.get('error_description')

  useEffect(() => {
    if (started.current) {
      return
    }
    started.current = true

    if (!auth.enabled) {
      setFailure('Authentication is off in this build, so there is nothing to complete.')
      return
    }
    // Cognito can reject the sign-in itself (a cancelled login, a bad scope). It comes back
    // as `?error=` rather than a code, and there is no state to check in that case.
    if (reportedError) {
      const message = errorDescription ?? reportedError
      setFailure(message)
      auth.reportError(message)
      return
    }
    if (!code || !state) {
      setFailure('The sign-in response is missing its code or state.')
      return
    }

    void auth
      .completeSignIn(code, state)
      .then((returnTo) => {
        navigate(returnTo, { replace: true })
      })
      .catch((thrown: unknown) => {
        setFailure(thrown instanceof Error ? thrown.message : String(thrown))
      })
  }, [auth, code, state, reportedError, errorDescription, navigate])

  if (failure) {
    return (
      <section className="card" aria-label="Sign-in failed">
        <h1>Sign-in failed</h1>
        <div className="state state--error" role="alert">
          <p className="state__title">The sign-in could not be completed</p>
          <p className="state__body">{failure}</p>
        </div>
        <p>
          <Link className="button button--primary" to="/login">
            Start again
          </Link>
        </p>
      </section>
    )
  }

  return (
    <section className="card" aria-label="Completing sign in">
      <h1>Signing you in…</h1>
      <Loading label="Completing the sign-in…" />
    </section>
  )
}
