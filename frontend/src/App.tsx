/**
 * The routes.
 *
 * Four screens, matching the four things the backend exposes: knowledge bases (which own
 * documents), one knowledge base (documents and asking), evaluation, and metrics. There is no
 * global state store and no data-fetching cache: each screen loads what it shows, and the
 * only navigation state is the URL.
 */

import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { EvaluationPage } from './features/evaluation/EvaluationPage'
import { KnowledgeBasePage } from './features/knowledge-bases/KnowledgeBasePage'
import { KnowledgeBasesPage } from './features/knowledge-bases/KnowledgeBasesPage'
import { MetricsPage } from './features/metrics/MetricsPage'

export function App(): ReactNode {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<KnowledgeBasesPage />} />
        <Route path="knowledge-bases/:knowledgeBaseId" element={<KnowledgeBasePage />} />
        <Route path="evaluations" element={<EvaluationPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
