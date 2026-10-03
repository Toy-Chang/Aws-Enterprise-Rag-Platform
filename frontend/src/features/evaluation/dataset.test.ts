import { describe, expect, it } from 'vitest'

import { parseDataset } from './dataset'

const VALID = JSON.stringify({
  name: 'runbooks',
  k: 5,
  documents: [{ name: 'policy.md', content: 'Credentials rotate every ninety days.' }],
  questions: [
    {
      id: 'q1',
      question: 'How often do credentials rotate?',
      answerable: true,
      relevant: [{ document: 'policy.md', contains: 'rotate every ninety days' }],
    },
  ],
})

describe('parseDataset', () => {
  it('accepts a well-formed dataset and keeps its values', () => {
    const parsed = parseDataset(VALID)

    expect(parsed.ok).toBe(true)
    if (!parsed.ok) {
      return
    }
    expect(parsed.request.name).toBe('runbooks')
    expect(parsed.request.k).toBe(5)
    expect(parsed.request.documents).toHaveLength(1)
    expect(parsed.request.questions[0]?.relevant).toHaveLength(1)
  })

  it('defaults the name and omits thresholds the dataset does not set', () => {
    const parsed = parseDataset(
      JSON.stringify({
        documents: [{ name: 'a.md', content: 'text' }],
        questions: [{ id: 'q', question: 'Why?', answerable: false }],
      }),
    )

    expect(parsed.ok).toBe(true)
    if (!parsed.ok) {
      return
    }
    expect(parsed.request.name).toBe('evaluation')
    expect(parsed.request.k).toBeUndefined()
    expect(parsed.request.min_score).toBeUndefined()
    // An absent label list becomes an empty one, which is what "unanswerable" means.
    expect(parsed.request.questions[0]?.relevant).toEqual([])
  })

  it('reports what is wrong instead of sending a payload the backend would reject', () => {
    const cases: [string, string][] = [
      ['', 'Paste a dataset'],
      ['{not json', 'Not valid JSON'],
      ['[]', 'must be a JSON object'],
      ['{}', 'documents must be a non-empty array'],
      [JSON.stringify({ documents: [] }), 'documents must be a non-empty array'],
      [JSON.stringify({ documents: [{ name: 'a.md' }] }), 'documents[0].content'],
      [JSON.stringify({ documents: [{ name: '', content: 'x' }] }), 'documents[0].name'],
      [JSON.stringify({ documents: 'x', questions: [] }), 'documents must be a non-empty array'],
      [
        JSON.stringify({ documents: [{ name: 'a.md', content: 'x' }] }),
        'questions must be a non-empty array',
      ],
      [
        JSON.stringify({
          documents: [{ name: 'a.md', content: 'x' }],
          questions: [{ id: 'q', question: 'Why?', answerable: 'yes' }],
        }),
        'answerable must be true or false',
      ],
      [
        JSON.stringify({
          documents: [{ name: 'a.md', content: 'x' }],
          questions: [{ question: 'Why?', answerable: true }],
        }),
        'questions[0].id',
      ],
      [
        JSON.stringify({
          documents: [{ name: 'a.md', content: 'x' }],
          questions: [
            {
              id: 'q',
              question: 'Why?',
              answerable: true,
              relevant: [{ document: 'a.md' }],
            },
          ],
        }),
        'questions[0].relevant[0].contains',
      ],
      [JSON.stringify({ documents: [{ name: 'a.md', content: 'x' }], questions: [], k: 'five' }), 'questions must be a non-empty array'],
      [
        JSON.stringify({
          documents: [{ name: 'a.md', content: 'x' }],
          questions: [{ id: 'q', question: 'Why?', answerable: false }],
          min_score: 'high',
        }),
        'min_score must be a number',
      ],
    ]

    for (const [text, expected] of cases) {
      const parsed = parseDataset(text)
      expect(parsed.ok, `expected ${expected} for ${text.slice(0, 40)}`).toBe(false)
      if (!parsed.ok) {
        expect(parsed.message).toContain(expected)
      }
    }
  })
})
