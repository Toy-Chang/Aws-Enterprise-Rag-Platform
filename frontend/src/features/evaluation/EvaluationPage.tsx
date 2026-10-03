/**
 * Running a labelled dataset and reading what it measured.
 *
 * The dataset is the source of truth for the request, and the two override fields exist for
 * the question this screen is for: what a different retrieval policy would have done. The
 * report always states the threshold it ran under, so a comparison cannot be misread.
 *
 * The corpus is ingested into a temporary knowledge base on the server and removed before the
 * response is returned, so nothing here can pollute what the query screen searches.
 */

import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, ReactNode } from 'react'

import { ApiError, asApiError } from '../../api/client'
import { api } from '../../api/endpoints'
import type { EvaluationRequest, EvaluationResponse } from '../../api/types'
import { ErrorState, Loading } from '../../components/states'
import { formatCount } from '../../lib/format'
import { parseDataset } from './dataset'
import { EvaluationReport } from './EvaluationReport'

const SAMPLE_PATH = `${import.meta.env.BASE_URL}sample-datasets/platform-runbooks-smoke.json`

function parseOptionalNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') {
    return null
  }
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : Number.NaN
}

export function EvaluationPage(): ReactNode {
  const [text, setText] = useState('')
  const [k, setK] = useState('')
  const [minScore, setMinScore] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<ApiError | null>(null)
  const [report, setReport] = useState<EvaluationResponse | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  async function loadSample(): Promise<void> {
    setProblem(null)
    try {
      const response = await fetch(SAMPLE_PATH)
      if (!response.ok) {
        setProblem(`The bundled sample could not be loaded (${response.status}).`)
        return
      }
      setText(await response.text())
    } catch (thrown) {
      setProblem(`The bundled sample could not be loaded: ${(thrown as Error).message}`)
    }
  }

  // Start with the committed sample so the screen is runnable without any preparation.
  useEffect(() => {
    void loadSample()
  }, [])

  async function run(event: FormEvent): Promise<void> {
    event.preventDefault()
    setRunError(null)
    setProblem(null)

    const parsed = parseDataset(text)
    if (!parsed.ok) {
      setProblem(parsed.message)
      return
    }

    const overrideK = parseOptionalNumber(k)
    const overrideMinScore = parseOptionalNumber(minScore)
    if (Number.isNaN(overrideK) || Number.isNaN(overrideMinScore)) {
      setProblem('Top-k and minimum score must be numbers when they are filled in.')
      return
    }
    if (overrideK !== null && (!Number.isInteger(overrideK) || overrideK < 1 || overrideK > 50)) {
      setProblem('Top-k must be a whole number between 1 and 50.')
      return
    }
    if (overrideMinScore !== null && (overrideMinScore < -1 || overrideMinScore > 1)) {
      setProblem('Minimum score must be between -1 and 1.')
      return
    }

    const request: EvaluationRequest = {
      ...parsed.request,
      ...(overrideK !== null ? { k: overrideK } : {}),
      ...(overrideMinScore !== null ? { min_score: overrideMinScore } : {}),
    }

    setRunning(true)
    setReport(null)
    try {
      setReport(await api.runEvaluation(request))
    } catch (thrown) {
      setRunError(asApiError(thrown))
    } finally {
      setRunning(false)
    }
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0]
    if (!file) {
      return
    }
    void file.text().then((content) => {
      setText(content)
      setProblem(null)
    })
  }

  return (
    <section>
      <h1>Evaluation</h1>
      <p className="card__hint">
        A dataset is a small corpus plus questions with explicit relevance labels. Running one
        ingests the corpus into a temporary knowledge base, asks every question through the
        same pipeline the query screen uses, and scores the result. Nothing is left behind.
      </p>

      <div className="card">
        <div className="card__header">
          <h2>Dataset</h2>
          <div className="row">
            <button
              type="button"
              className="button button--small"
              onClick={() => void loadSample()}
            >
              Load the bundled sample
            </button>
            <label className="button button--small" htmlFor="dataset-file">
              Choose a file…
            </label>
            <input
              id="dataset-file"
              ref={fileInput}
              type="file"
              accept=".json,application/json"
              style={{ display: 'none' }}
              onChange={chooseFile}
            />
          </div>
        </div>

        <form onSubmit={(event) => void run(event)}>
          <div className="field">
            <label htmlFor="dataset">Dataset JSON (documents, questions, relevance labels)</label>
            <textarea
              id="dataset"
              rows={14}
              spellCheck={false}
              value={text}
              onChange={(event) => {
                setText(event.target.value)
              }}
            />
          </div>

          <div className="row" style={{ marginTop: '0.6rem' }}>
            <div className="field">
              <label htmlFor="evaluation-k">Passages (k) override</label>
              <input
                id="evaluation-k"
                inputMode="numeric"
                value={k}
                placeholder="from the dataset, else the server default"
                onChange={(event) => {
                  setK(event.target.value)
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="evaluation-min-score">Minimum score override</label>
              <input
                id="evaluation-min-score"
                inputMode="decimal"
                value={minScore}
                placeholder="server default"
                onChange={(event) => {
                  setMinScore(event.target.value)
                }}
              />
            </div>
            <button type="submit" className="button button--primary" disabled={running}>
              {running ? 'Running…' : 'Run evaluation'}
            </button>
          </div>
        </form>

        {problem ? (
          <p className="state state--error" role="alert">
            {problem}
          </p>
        ) : null}
        {runError ? <ErrorState error={runError} /> : null}
        {running ? (
          <Loading label="Ingesting the corpus and asking every question…" />
        ) : null}
        <p className="card__hint" style={{ marginBottom: 0 }}>
          The backend validates the dataset again and refuses one that contradicts itself — a
          label naming a document that is not in the corpus, an answerable question with no
          label, or an unanswerable one that labels evidence.
        </p>
      </div>

      {report ? <EvaluationReport report={report} /> : null}

      {!report && !running ? (
        <p className="card__hint">
          The bundled sample is a smoke dataset: {formatCount(5)} short runbook documents and{' '}
          {formatCount(6)} questions, one of which the corpus does not answer. It demonstrates
          the format and exercises the pipeline; it is not evidence of retrieval quality.
        </p>
      ) : null}
    </section>
  )
}
