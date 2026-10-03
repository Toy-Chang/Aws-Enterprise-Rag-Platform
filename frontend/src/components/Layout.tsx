/**
 * The shell: identity, navigation, and whether the API is actually answering.
 *
 * The status badge is not decoration. Everything else on the page is a read of the API, so
 * "the API is unreachable" is the difference between an empty platform and a stopped
 * backend, and it is the first thing an operator needs to know.
 */

import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { api } from '../api/endpoints'
import { useAsync } from '../lib/useAsync'
import { SignedInAs } from './SignedInAs'

function ApiStatus(): ReactNode {
  const health = useAsync((signal) => api.liveness(signal), [])

  if (health.loading) {
    return <span className="badge badge--muted">API: checking…</span>
  }
  if (health.error) {
    return (
      <span className="badge badge--error" title={health.error.message}>
        API: unreachable ({health.error.code})
      </span>
    )
  }
  return (
    <span className="badge badge--ok">
      API {health.data?.version} · {health.data?.environment}
    </span>
  )
}

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? 'nav__link nav__link--active' : 'nav__link'
}

export function Layout(): ReactNode {
  return (
    <div className="app">
      <header className="app__header">
        <div className="app__brand">
          <span className="app__title">AWS Enterprise RAG Platform</span>
          <span className="app__subtitle">Answers built only from your own documents</span>
        </div>
        <div className="app__status">
          <SignedInAs />
          <ApiStatus />
        </div>
      </header>

      <nav className="nav" aria-label="Sections">
        <NavLink to="/" end className={navClass}>
          Knowledge bases
        </NavLink>
        <NavLink to="/evaluations" className={navClass}>
          Evaluation
        </NavLink>
        <NavLink to="/metrics" className={navClass}>
          Metrics
        </NavLink>
      </nav>

      <main className="app__main">
        <Outlet />
      </main>

      <footer className="app__footer">
        Every answer carries its citations and a per-stage trace. A question the knowledge base
        does not support is reported as <code>insufficient_evidence</code> rather than answered.
      </footer>
    </div>
  )
}
