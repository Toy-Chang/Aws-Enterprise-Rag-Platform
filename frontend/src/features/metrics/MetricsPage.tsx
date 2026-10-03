/**
 * `GET /api/v1/metrics`: what this process has actually recorded.
 *
 * Three things are stated on the page because they change how the numbers should be read:
 * the snapshot is per process (a second replica has its own counters), it does not survive a
 * restart, and the percentiles describe a bounded window of recent samples — which is why
 * `observed` and `retained` sit next to every summary. A stage that never ran has no latency
 * row at all rather than a row of zeros.
 */

import type { ReactNode } from 'react'

import { api } from '../../api/endpoints'
import type { LatencySummary, MetricsResponse } from '../../api/types'
import { EmptyState, ErrorState, Loading } from '../../components/states'
import { formatCount, formatMs } from '../../lib/format'
import { useAsync } from '../../lib/useAsync'

const GROUP_ORDER = ['http', 'ingestion', 'query', 'retrieval', 'generation', 'evaluation']

function groupOf(name: string): string {
  const separator = name.indexOf('.')
  return separator === -1 ? name : name.slice(0, separator)
}

function groupRank(group: string): number {
  const index = GROUP_ORDER.indexOf(group)
  return index === -1 ? GROUP_ORDER.length : index
}

/** Counters by their first segment, each group in a stable order. */
function groupCounters(counters: Record<string, number>): [string, [string, number][]][] {
  const groups = new Map<string, [string, number][]>()
  for (const entry of Object.entries(counters)) {
    const group = groupOf(entry[0])
    const bucket = groups.get(group)
    if (bucket) {
      bucket.push(entry)
    } else {
      groups.set(group, [entry])
    }
  }
  return [...groups.entries()]
    .map(([group, entries]) => [group, entries.sort((a, b) => a[0].localeCompare(b[0]))] as [string, [string, number][]])
    .sort((a, b) => groupRank(a[0]) - groupRank(b[0]) || a[0].localeCompare(b[0]))
}

function LatencyTable({ latencies }: { latencies: Record<string, LatencySummary> }): ReactNode {
  const rows = Object.entries(latencies).sort((a, b) => a[0].localeCompare(b[0]))
  return (
    <div className="table-scroll">
      <table aria-label="Latency">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="numeric">Observed</th>
            <th className="numeric">Retained</th>
            <th className="numeric">Mean</th>
            <th className="numeric">p50</th>
            <th className="numeric">p95</th>
            <th className="numeric">Max</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, summary]) => (
            <tr key={name}>
              <td className="mono">{name}</td>
              <td className="numeric">{formatCount(summary.observed)}</td>
              <td className="numeric">{formatCount(summary.retained)}</td>
              <td className="numeric">{formatMs(summary.mean_ms)}</td>
              <td className="numeric">{formatMs(summary.p50_ms)}</td>
              <td className="numeric">{formatMs(summary.p95_ms)}</td>
              <td className="numeric">{formatMs(summary.max_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MetricsPage(): ReactNode {
  const metrics = useAsync((signal) => api.metrics(signal), [])
  const snapshot: MetricsResponse | null = metrics.data
  const groups = snapshot ? groupCounters(snapshot.counters) : []
  const latencyNames = snapshot ? Object.keys(snapshot.latencies) : []
  const hasAnything = snapshot
    ? Object.keys(snapshot.counters).length > 0 || latencyNames.length > 0
    : false

  return (
    <section>
      <div className="card">
        <div className="card__header">
          <h1>Metrics</h1>
          <button type="button" className="button button--small" onClick={metrics.reload}>
            Refresh
          </button>
        </div>
        <p className="card__hint">
          Counters and latency summaries recorded by this process since it started. They are not
          aggregated across replicas and do not survive a restart — in a deployment, CloudWatch
          is the record. Percentiles are nearest-rank over the last{' '}
          {snapshot ? formatCount(snapshot.window) : '—'} samples per metric, so a reported
          percentile is always a value that was measured.
        </p>
        <p className="card__hint" style={{ marginBottom: 0 }}>
          Counters are labelled by route template and never by an identifier, so the number of
          series cannot grow with traffic. The request that reads this endpoint appears as a
          request here but not yet as a response: it is recorded once it finishes, after this
          snapshot was taken.
        </p>
      </div>

      {metrics.loading ? <Loading label="Loading metrics…" /> : null}
      {metrics.error ? <ErrorState error={metrics.error} onRetry={metrics.reload} /> : null}

      {snapshot && !hasAnything ? (
        <EmptyState title="Nothing recorded yet">
          <p>
            Counters appear as soon as this process handles a request. Create a knowledge base
            or ask a question and refresh.
          </p>
        </EmptyState>
      ) : null}

      {groups.map(([group, entries]) => (
        <div className="card" key={group}>
          <div className="card__header">
            <h2>{group}</h2>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Counter</th>
                  <th className="numeric">Value</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([name, value]) => (
                  <tr key={name}>
                    <td className="mono">{name}</td>
                    <td className="numeric">{formatCount(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {snapshot && latencyNames.length > 0 ? (
        <div className="card">
          <div className="card__header">
            <h2>Latency</h2>
          </div>
          <LatencyTable latencies={snapshot.latencies} />
          <p className="card__hint" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
            <code>observed</code> counts every measurement taken; <code>retained</code> is how
            many the summary was computed from. A stage that never ran has no row here rather
            than a zero: no evidence means no generation, and that is visible in the counters
            instead.
          </p>
        </div>
      ) : null}
    </section>
  )
}
