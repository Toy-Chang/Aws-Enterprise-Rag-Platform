import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderPage } from '../../test/api'
import { evaluationResponse } from '../../test/fixtures'
import { EvaluationReport } from './EvaluationReport'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('EvaluationReport', () => {
  it('shows the corpus, the policy the run used and every retrieval metric', () => {
    renderPage(<EvaluationReport report={evaluationResponse()} />)

    expect(screen.getByRole('heading', { name: 'platform-runbooks-smoke' })).toBeInTheDocument()
    // The threshold is on the page, because a number without its policy cannot be read.
    expect(screen.getByText(/k 5 · min_score 0\.100/)).toBeInTheDocument()
    expect(screen.getByText(/5 documents ingested into 19 passages/)).toBeInTheDocument()
    expect(screen.getByText('recall@5')).toBeInTheDocument()
    const precisionTile = screen.getByText('precision@5').closest('.tile')
    expect(precisionTile).not.toBeNull()
    expect(within(precisionTile as HTMLElement).getByText('0.200')).toBeInTheDocument()
    expect(screen.getByText(/divided by k = 5/)).toBeInTheDocument()
    expect(screen.getByText('nDCG@5')).toBeInTheDocument()
  })

  it('renders a rate with no observations as a dash, not as a percentage', () => {
    const report = evaluationResponse({
      answers: {
        answered: 5,
        insufficient_evidence: 0,
        answerable_answered: 1,
        unanswerable_abstained: null,
        citation_precision: null,
        citation_recall: null,
      },
    })

    renderPage(<EvaluationReport report={report} />)

    const tile = screen.getByText('unanswerable abstained').closest('.tile')
    expect(tile).not.toBeNull()
    expect(within(tile as HTMLElement).getByText('—')).toBeInTheDocument()
  })

  it('reports the generation latency as absent when nothing reached the generator', () => {
    const report = evaluationResponse({
      latency: {
        ...evaluationResponse().latency,
        generation_ms: null,
      },
    })

    renderPage(<EvaluationReport report={report} />)

    const row = screen.getByRole('row', { name: /^Generation/ })
    for (const cell of within(row).getAllByRole('cell').slice(1)) {
      expect(cell.textContent).toBe('—')
    }
  })

  it('lists dataset problems, which are not scored as retrieval misses', () => {
    const report = evaluationResponse({
      issues: ["no chunk of 'policy.md' contains the labelled snippet"],
    })

    renderPage(<EvaluationReport report={report} />)

    expect(screen.getByText('Dataset problems')).toBeInTheDocument()
    expect(screen.getByText(/no chunk of 'policy\.md'/)).toBeInTheDocument()
    expect(screen.getByText(/leaves its question out of the retrieval averages/)).toBeInTheDocument()
  })

  it('shows an unscorable question as unmeasured rather than as a zero', () => {
    renderPage(<EvaluationReport report={evaluationResponse()} />)

    const row = screen.getByRole('row', { name: /holiday-schedule/ })
    expect(within(row).getByText('not answerable')).toBeInTheDocument()
    // Recall, precision, reciprocal rank and nDCG are unmeasured for this question, so each
    // is a dash. The citation cell also carries its count, so it is checked separately.
    const cells = within(row).getAllByRole('cell')
    expect(cells.filter((cell) => cell.textContent === '—')).toHaveLength(4)
    expect(within(row).getByText(/5 cited · recall —/)).toBeInTheDocument()
  })

  it('says that no faithfulness metric is reported, rather than leaving a gap', () => {
    renderPage(<EvaluationReport report={evaluationResponse()} />)

    expect(screen.getByText(/no faithfulness metric is shown/)).toBeInTheDocument()
  })
})
