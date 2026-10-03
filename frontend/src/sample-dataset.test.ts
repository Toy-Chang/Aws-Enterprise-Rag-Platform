/**
 * The bundled sample dataset must be the committed one.
 *
 * The Evaluation screen ships a copy of `evaluation/datasets/sample.json` in `public/` so the
 * page is runnable without preparing anything. A copy can drift, and a drifting sample would
 * quietly stop being the dataset the README and the backend tests describe, so this test
 * compares the two files byte for byte.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// Resolved from the project root, which is the working directory of the frontend test run.
// `import.meta.url` is not a file URL under the jsdom environment, so it cannot be used here.
const backendSample = resolve(process.cwd(), '../evaluation/datasets/sample.json')
const bundledSample = resolve(process.cwd(), 'public/sample-datasets/platform-runbooks-smoke.json')

describe('the bundled sample dataset', () => {
  it('is identical to the dataset the backend repository commits', () => {
    const backend = readFileSync(backendSample, 'utf8')
    const bundled = readFileSync(bundledSample, 'utf8')

    expect(bundled).toBe(backend)
  })

  it('is a dataset the backend would accept', () => {
    const dataset = JSON.parse(readFileSync(bundledSample, 'utf8')) as {
      name: string
      k: number
      documents: { name: string; content: string }[]
      questions: { id: string; answerable: boolean; relevant: { document: string }[] }[]
    }

    expect(dataset.name).toBe('platform-runbooks-smoke')
    expect(dataset.documents.length).toBeGreaterThan(0)
    expect(dataset.questions.length).toBeGreaterThan(0)

    const names = new Set(dataset.documents.map((document) => document.name))
    for (const question of dataset.questions) {
      // An answerable question labels evidence; an unanswerable one labels none. A label
      // naming a document that is not in the corpus is rejected by the backend.
      expect(question.answerable).toBe(question.relevant.length > 0)
      for (const label of question.relevant) {
        expect(names.has(label.document)).toBe(true)
      }
    }
  })
})
