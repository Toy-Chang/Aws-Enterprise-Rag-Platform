/**
 * Reading a dataset the operator pasted or picked.
 *
 * This is a convenience, not the authority. It catches the mistakes that are obvious locally
 * — not JSON, no documents, a question without an id — so the run button can explain itself
 * without a round trip. The backend validates the same payload again and rejects anything
 * that would make the metrics meaningless (a label naming a document the corpus does not
 * contain, an answerable question that labels nothing), and that rejection is what is shown
 * if the two ever disagree.
 */

import type { EvaluationDocument, EvaluationLabel, EvaluationQuestion, EvaluationRequest } from '../../api/types'

export type ParsedDataset =
  | { ok: true; request: EvaluationRequest }
  | { ok: false; message: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readString(
  source: Record<string, unknown>,
  key: string,
  where: string,
): { ok: true; value: string } | { ok: false; message: string } {
  const value = source[key]
  if (typeof value !== 'string' || value.trim() === '') {
    return { ok: false, message: `${where}.${key} must be a non-empty string.` }
  }
  return { ok: true, value }
}

function readDocuments(value: unknown): { ok: true; value: EvaluationDocument[] } | { ok: false; message: string } {
  if (!Array.isArray(value) || value.length === 0) {
    return { ok: false, message: 'documents must be a non-empty array.' }
  }
  const documents: EvaluationDocument[] = []
  for (const [index, entry] of value.entries()) {
    if (!isRecord(entry)) {
      return { ok: false, message: `documents[${index}] must be an object.` }
    }
    const name = readString(entry, 'name', `documents[${index}]`)
    if (!name.ok) {
      return name
    }
    const content = readString(entry, 'content', `documents[${index}]`)
    if (!content.ok) {
      return content
    }
    documents.push({ name: name.value, content: content.value })
  }
  return { ok: true, value: documents }
}

function readLabels(value: unknown, where: string): { ok: true; value: EvaluationLabel[] } | { ok: false; message: string } {
  if (value === undefined) {
    return { ok: true, value: [] }
  }
  if (!Array.isArray(value)) {
    return { ok: false, message: `${where}.relevant must be an array.` }
  }
  const labels: EvaluationLabel[] = []
  for (const [index, entry] of value.entries()) {
    if (!isRecord(entry)) {
      return { ok: false, message: `${where}.relevant[${index}] must be an object.` }
    }
    const document = readString(entry, 'document', `${where}.relevant[${index}]`)
    if (!document.ok) {
      return document
    }
    const contains = readString(entry, 'contains', `${where}.relevant[${index}]`)
    if (!contains.ok) {
      return contains
    }
    labels.push({ document: document.value, contains: contains.value })
  }
  return { ok: true, value: labels }
}

function readQuestions(value: unknown): { ok: true; value: EvaluationQuestion[] } | { ok: false; message: string } {
  if (!Array.isArray(value) || value.length === 0) {
    return { ok: false, message: 'questions must be a non-empty array.' }
  }
  const questions: EvaluationQuestion[] = []
  for (const [index, entry] of value.entries()) {
    const where = `questions[${index}]`
    if (!isRecord(entry)) {
      return { ok: false, message: `${where} must be an object.` }
    }
    const id = readString(entry, 'id', where)
    if (!id.ok) {
      return id
    }
    const question = readString(entry, 'question', where)
    if (!question.ok) {
      return question
    }
    if (typeof entry.answerable !== 'boolean') {
      return { ok: false, message: `${where}.answerable must be true or false.` }
    }
    const labels = readLabels(entry.relevant, where)
    if (!labels.ok) {
      return labels
    }
    questions.push({
      id: id.value,
      question: question.value,
      answerable: entry.answerable,
      relevant: labels.value,
    })
  }
  return { ok: true, value: questions }
}

function readOptionalNumber(
  source: Record<string, unknown>,
  key: string,
  fallback: number | null,
): { ok: true; value: number | null } | { ok: false; message: string } {
  const value = source[key]
  if (value === undefined || value === null) {
    return { ok: true, value: fallback }
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return { ok: false, message: `${key} must be a number.` }
  }
  return { ok: true, value }
}

export function parseDataset(text: string): ParsedDataset {
  if (text.trim() === '') {
    return { ok: false, message: 'Paste a dataset, choose a file, or load the bundled sample.' }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (thrown) {
    return { ok: false, message: `Not valid JSON: ${(thrown as Error).message}` }
  }

  if (!isRecord(parsed)) {
    return { ok: false, message: 'The dataset must be a JSON object.' }
  }

  const documents = readDocuments(parsed.documents)
  if (!documents.ok) {
    return documents
  }
  const questions = readQuestions(parsed.questions)
  if (!questions.ok) {
    return questions
  }

  const name = parsed.name === undefined ? 'evaluation' : readString(parsed, 'name', 'dataset')
  if (typeof name !== 'string' && !name.ok) {
    return name
  }
  const k = readOptionalNumber(parsed, 'k', null)
  if (!k.ok) {
    return k
  }
  const minScore = readOptionalNumber(parsed, 'min_score', null)
  if (!minScore.ok) {
    return minScore
  }

  return {
    ok: true,
    request: {
      name: typeof name === 'string' ? name : name.value,
      ...(k.value !== null ? { k: k.value } : {}),
      ...(minScore.value !== null ? { min_score: minScore.value } : {}),
      documents: documents.value,
      questions: questions.value,
    },
  }
}
