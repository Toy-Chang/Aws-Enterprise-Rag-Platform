/**
 * The route guard.
 *
 * It wraps the authenticated screens and does one thing: when authentication is on and this
 * tab holds no session, it renders the sign-in card and the children never mount — so no
 * screen fires an unauthenticated request that can only come back `401`.
 *
 * Rendering instead of redirecting is deliberate. A redirect to `/login` from a page load
 * loses nothing, but a render-phase swap also handles the case where the session is cleared
 * *during* a later request: React re-renders, the guard takes over, and the page that was
 * about to show a broken error is replaced before it can. The user still has to click one
 * thing, which is a fair price for not bouncing through a URL the user did not ask for.
 *
 * When authentication is off, this is a pass-through and the app is exactly what it was.
 */

import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { SignInPrompt } from './SignInPrompt'

export function RequireAuth({ children }: { children: ReactNode }): ReactNode {
  const auth = useAuth()
  const location = useLocation()

  if (!auth.enabled) {
    return <>{children}</>
  }
  if (auth.session) {
    return <>{children}</>
  }
  return (
    <SignInPrompt
      returnTo={`${location.pathname}${location.search}`}
      message="Sign in to use this console."
    />
  )
}
