/**
 * Display formatting, kept in one place and deliberately explicit.
 *
 * Everything here is deterministic: timestamps are rendered as UTC in the same shape the
 * backend logs use, and numbers use an explicit `en-US` locale, so a screenshot, a log line
 * and a test all show the same string. `null` means "not measured" throughout the API and
 * renders as an em dash rather than as a zero.
 */

const NOT_MEASURED = '—'

export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

export function formatMs(value: number): string {
  if (!Number.isFinite(value)) {
    return NOT_MEASURED
  }
  if (value < 1) {
    return `${value.toFixed(3)} ms`
  }
  if (value < 100) {
    return `${value.toFixed(2)} ms`
  }
  return `${value.toFixed(1)} ms`
}

export function formatScore(value: number | null, digits = 3): string {
  return value === null ? NOT_MEASURED : value.toFixed(digits)
}

/** A rate between 0 and 1 as a percentage. Null is "no observations", not "0%". */
export function formatRate(value: number | null): string {
  return value === null ? NOT_MEASURED : `${(value * 100).toFixed(1)}%`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}

/** UTC, second precision, in the shape the structured logs use. */
export function formatTimestamp(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) {
    return iso
  }
  return `${parsed.toISOString().slice(0, 19).replace('T', ' ')}Z`
}

export function formatTokens(input: number | null, output: number | null): string {
  if (input === null && output === null) {
    return 'not reported'
  }
  return `${input ?? 0} in / ${output ?? 0} out`
}

export { NOT_MEASURED }
