/**
 * What one evaluation run measured.
 *
 * Two conventions are stated on the page rather than left to be inferred, because both make
 * numbers that look wrong look right:
 *
 * - `precision_at_k` divides by `k`, so a question with one relevant passage and `k = 5`
 *   reports 0.2 even when the relevant passage was found first.
 * - A dash is "no observation", not zero. A dataset with no unanswerable question has not
 *   shown that the platform abstains, so `unanswerable_abstained` is `null` and is shown as a
 *   dash.
 *
 * No faithfulness or hallucination number appears anywhere, because none is computed: judging
 * whether an answer's prose is supported by its citations needs a human or a model, and this
 * report contains only what follows from the labels.
 */

import type { ReactNode } from 'react'

import type { EvaluationResponse, QuestionResult, Summary } from '../../api/types'
import { formatCount, formatMs, formatRate, formatScore } from '../../lib/format'

function Tile({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}): ReactNode {
  return (
    <div className="tile">
      <div className="tile__label">{label}</div>
      <div className="tile__value">{value}</div>
      {hint ? <div className="tile__hint">{hint}</div> : null}
    </div>
  )
}

function LatencyRow({ label, summary }: { label: string; summary: Summary | null }): ReactNode {
  return (
    <tr>
      <td>{label}</td>
      {summary ? (
        <>
          <td className="numeric">{formatCount(summary.count)}</td>
          <td className="numeric">{formatMs(summary.mean)}</td>
          <td className="numeric">{formatMs(summary.p50)}</td>
          <td className="numeric">{formatMs(summary.p95)}</td>
          <td className="numeric">{formatMs(summary.maximum)}</td>
        </>
      ) : (
        <>
          <td className="numeric">—</td>
          <td className="numeric">—</td>
          <td className="numeric">—</td>
          <td className="numeric">—</td>
          <td className="numeric">—</td>
        </>
      )}
    </tr>
  )
}

function QuestionRow({ question }: { question: QuestionResult }): ReactNode {
  return (
    <tr>
      <td>
        <span className="mono">{question.id}</span>
        <div style={{ color: 'var(--text-muted)' }}>{question.question}</div>
        {question.issues.map((issue) => (
          <div key={issue} style={{ color: 'var(--warn)' }}>
            {issue}
          </div>
        ))}
      </td>
      <td>
        {question.answerable ? 'answerable' : 'not answerable'}
        <div className="mono" style={{ color: 'var(--text-muted)' }}>
          {question.outcome}
        </div>
      </td>
      <td className="numeric">{formatCount(question.relevant_chunks)}</td>
      <td className="numeric">
        {formatCount(question.retrieved_chunks)}
        {question.matched_chunks !== null ? (
          <div style={{ color: 'var(--text-muted)' }}>{question.matched_chunks} matched</div>
        ) : null}
      </td>
      <td className="numeric">{formatScore(question.recall_at_k)}</td>
      <td className="numeric">{formatScore(question.precision_at_k)}</td>
      <td className="numeric">{formatScore(question.reciprocal_rank)}</td>
      <td className="numeric">{formatScore(question.ndcg_at_k)}</td>
      <td className="numeric">
        {formatScore(question.citation_precision)}
        <div style={{ color: 'var(--text-muted)' }}>
          {question.citations} cited · recall {formatScore(question.citation_recall)}
        </div>
      </td>
      <td className="numeric">
        {formatMs(question.total_ms)}
        <div style={{ color: 'var(--text-muted)' }}>
          {question.generation_ms === null ? 'no generation' : formatMs(question.generation_ms)}
        </div>
      </td>
    </tr>
  )
}

export function EvaluationReport({ report }: { report: EvaluationResponse }): ReactNode {
  const { retrieval, answers } = report

  return (
    <section>
      <div className="card">
        <div className="card__header">
          <h2>{report.dataset}</h2>
          <span className="mono" style={{ color: 'var(--text-muted)' }}>
            k {report.k} · min_score {formatScore(report.min_score)}
          </span>
        </div>
        <p className="card__hint">
          {formatCount(report.documents)} documents ingested into {formatCount(report.chunks)}{' '}
          passages · {formatCount(report.total_questions)} questions ({formatCount(report.answerable)}{' '}
          answerable, {formatCount(report.unanswerable)} not). The temporary knowledge base{' '}
          <span className="mono">{report.temporary_knowledge_base_id}</span> was removed before
          this report was returned.
        </p>

        {report.issues.length > 0 ? (
          <div className="state state--error" role="alert">
            <p className="state__title">Dataset problems</p>
            <ul className="issues">
              {report.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
            <p className="state__body">
              These affected the run: an unresolvable label leaves its question out of the
              retrieval averages instead of scoring it as a miss.
            </p>
          </div>
        ) : null}
      </div>

      <div className="card">
        <div className="card__header">
          <h2>Retrieval and answers</h2>
        </div>
        {retrieval ? (
          <div className="grid">
            <Tile label={`recall@${retrieval.k}`} value={retrieval.recall_at_k.toFixed(3)} hint={`over ${retrieval.questions} scorable questions`} />
            <Tile
              label={`precision@${retrieval.k}`}
              value={retrieval.precision_at_k.toFixed(3)}
              hint={`divided by k = ${retrieval.k}`}
            />
            <Tile label={`hit rate@${retrieval.k}`} value={retrieval.hit_rate_at_k.toFixed(3)} hint="questions with at least one relevant passage" />
            <Tile label="MRR" value={retrieval.mrr.toFixed(3)} hint="reciprocal rank of the first relevant passage" />
            <Tile label={`nDCG@${retrieval.k}`} value={retrieval.ndcg_at_k.toFixed(3)} hint="binary gains, ideal from all relevant passages" />
          </div>
        ) : (
          <p className="state state--empty">
            No question had a resolvable label, so no retrieval metric could be computed.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card__header">
          <h2>Answer behaviour</h2>
        </div>
        <div className="grid">
          <Tile label="answered" value={formatCount(answers.answered)} hint={`${formatCount(answers.insufficient_evidence)} reported missing evidence`} />
          <Tile label="answerable answered" value={formatRate(answers.answerable_answered)} hint="of the questions the corpus answers" />
          <Tile label="unanswerable abstained" value={formatRate(answers.unanswerable_abstained)} hint="of the questions it does not" />
          <Tile label="citation precision" value={formatRate(answers.citation_precision)} hint="cited passages the labels mark relevant" />
          <Tile label="citation recall" value={formatRate(answers.citation_recall)} hint="labelled passages that were cited" />
        </div>
        <p className="card__hint" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          A dash means no observation rather than zero, and no faithfulness metric is shown:
          whether an answer&apos;s prose is supported by its citations is not something these
          labels can decide.
        </p>
      </div>

      <div className="card">
        <div className="card__header">
          <h2>Latency</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Stage</th>
                <th className="numeric">Count</th>
                <th className="numeric">Mean</th>
                <th className="numeric">p50</th>
                <th className="numeric">p95</th>
                <th className="numeric">Max</th>
              </tr>
            </thead>
            <tbody>
              <LatencyRow label="Retrieval" summary={report.latency.retrieval_ms} />
              <LatencyRow label="Generation" summary={report.latency.generation_ms} />
              <LatencyRow label="Total" summary={report.latency.total_ms} />
            </tbody>
          </table>
        </div>
        <p className="card__hint" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          Generation has no row when no question reached the generator, rather than a row of
          zeros.
        </p>
      </div>

      <div className="card">
        <div className="card__header">
          <h2>Per question</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Question</th>
                <th>Kind</th>
                <th className="numeric">Relevant</th>
                <th className="numeric">Retrieved</th>
                <th className="numeric">Recall</th>
                <th className="numeric">Precision</th>
                <th className="numeric">RR</th>
                <th className="numeric">nDCG</th>
                <th className="numeric">Citation</th>
                <th className="numeric">Total</th>
              </tr>
            </thead>
            <tbody>
              {report.per_question.map((question) => (
                <QuestionRow key={question.id} question={question} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
