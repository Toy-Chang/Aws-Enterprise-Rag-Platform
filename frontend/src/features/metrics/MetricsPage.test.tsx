import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { errorEnvelope, json, renderPage, stubApi } from '../../test/api'
import { metricsResponse } from '../../test/fixtures'
import { MetricsPage } from './MetricsPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MetricsPage', () => {
  it('groups counters by their first segment and shows latency with observed and retained', async () => {
    stubApi([{ url: '/api/v1/metrics', response: () => json(metricsResponse()) }])

    renderPage(<MetricsPage />)

    // Counters are grouped under a heading per prefix, in a stable order.
    const headings = await screen.findAllByRole('heading', { level: 2 })
    expect(headings.map((heading) => heading.textContent)).toEqual([
      'http',
      'ingestion',
      'query',
      'evaluation',
      'Latency',
    ])

    expect(screen.getByText('http.route.unmatched')).toBeInTheDocument()
    // The window size is stated in the explanatory text, which is where it belongs.
    expect(screen.getByText(/1,024 samples per metric/)).toBeInTheDocument()

    // Scoped to the latency table: the counter tables have `query.*` rows too. The cells are
    // observed, retained, mean, p50, p95 and max, in that order.
    const latency = screen.getByRole('table', { name: 'Latency' })
    const queryRow = within(latency).getByRole('row', { name: /^query/ })
    expect(within(queryRow).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      'query',
      '4',
      '4',
      '0.700 ms',
      '0.600 ms',
      '1.00 ms',
      '1.00 ms',
    ])
  })

  it('states that the numbers are per process and windowed', async () => {
    stubApi([{ url: '/api/v1/metrics', response: () => json(metricsResponse()) }])

    renderPage(<MetricsPage />)

    expect(await screen.findByText(/nearest-rank over the last/)).toBeInTheDocument()
    expect(screen.getByText(/do not survive a restart/)).toBeInTheDocument()
  })

  it('explains an empty snapshot instead of showing an empty table', async () => {
    stubApi([
      { url: '/api/v1/metrics', response: () => json(metricsResponse({ counters: {}, latencies: {} })) },
    ])

    renderPage(<MetricsPage />)

    expect(await screen.findByText('Nothing recorded yet')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows the error envelope with its code and request id', async () => {
    stubApi([
      {
        url: '/api/v1/metrics',
        response: () => errorEnvelope('INTERNAL_ERROR', 'Something failed.', {}, 500, 'req-42'),
      },
    ])

    renderPage(<MetricsPage />)

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('INTERNAL_ERROR')).toBeInTheDocument()
    expect(screen.getByText('req-42')).toBeInTheDocument()
  })

  it('refetches when the operator asks for a fresh snapshot', async () => {
    const { calls } = stubApi([
      { url: '/api/v1/metrics', response: () => json(metricsResponse()) },
    ])
    const user = userEvent.setup()

    renderPage(<MetricsPage />)
    await screen.findByText('http.route.unmatched')
    await user.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(calls.filter((call) => call.url === '/api/v1/metrics')).toHaveLength(2)
  })
})
