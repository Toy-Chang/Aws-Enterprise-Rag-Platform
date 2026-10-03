/**
 * The routes.
 *
 * Four screens, matching the four things the backend exposes: knowledge bases (which own
 * documents), one knowledge base (documents and asking), evaluation, and metrics. There is no
 * global state store and no data-fetching cache: each screen loads what it shows, and the
 * only navigation state is the URL.
 *
 * Authentication adds two routes outside the shell — `/login` and `/callback` are the
 * redirect endpoints, and rendering a header full of navigation around a sign-in card would
 * only offer links that cannot work yet. `RequireAuth` wraps the shell, so every screen
 * behind it is guarded at once and no screen has to remember to check.
 */

import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { RequireAuth } from './components/RequireAuth'
import { Layout } from './components/Layout'
import { CallbackPage } from './features/auth/CallbackPage'
import { LoginPage } from './features/auth/LoginPage'
import { EvaluationPage } from './features/evaluation/EvaluationPage'
import { KnowledgeBasePage } from './features/knowledge-bases/KnowledgeBasePage'
import { KnowledgeBasesPage } from './features/knowledge-bases/KnowledgeBasesPage'
import { MetricsPage } from './features/metrics/MetricsPage'

export function App(): ReactNode {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route path="callback" element={<CallbackPage />} />

      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<KnowledgeBasesPage />} />
        <Route path="knowledge-bases/:knowledgeBaseId" element={<KnowledgeBasePage />} />
        <Route path="evaluations" element={<EvaluationPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
