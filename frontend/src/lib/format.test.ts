import { describe, expect, it } from 'vitest'

import {
  formatBytes,
  formatCount,
  formatMs,
  formatRate,
  formatScore,
  formatTimestamp,
  formatTokens,
} from './format'

describe('formatMs', () => {
  it('keeps resolution where the number is small and drops it where it is not', () => {
    expect(formatMs(0.009)).toBe('0.009 ms')
    expect(formatMs(1.797)).toBe('1.80 ms')
    expect(formatMs(25.231)).toBe('25.23 ms')
    expect(formatMs(1234.5)).toBe('1234.5 ms')
  })

  it('never reports a non-finite measurement as a number', () => {
    expect(formatMs(Number.NaN)).toBe('—')
  })
})

describe('null means not measured', () => {
  it('renders rates, scores and tokens as an em dash rather than as zero', () => {
    expect(formatRate(null)).toBe('—')
    expect(formatScore(null)).toBe('—')
    expect(formatTokens(null, null)).toBe('not reported')
  })

  it('formats a real rate as a percentage with one decimal', () => {
    expect(formatRate(1)).toBe('100.0%')
    expect(formatRate(0.26)).toBe('26.0%')
    expect(formatRate(0)).toBe('0.0%')
  })

  it('formats scores with three decimals by default', () => {
    expect(formatScore(0.369274)).toBe('0.369')
    expect(formatScore(1)).toBe('1.000')
  })
})

describe('formatBytes', () => {
  it('scales through bytes, KiB and MiB', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1500)).toBe('1.5 KiB')
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MiB')
  })
})

describe('formatTimestamp', () => {
  it('renders UTC in the shape the backend logs use, not the browser locale', () => {
    expect(formatTimestamp('2026-01-01T09:30:00Z')).toBe('2026-01-01 09:30:00Z')
    expect(formatTimestamp('2026-01-01T09:30:00.123456Z')).toBe('2026-01-01 09:30:00Z')
  })

  it('passes through something that is not a date rather than printing Invalid Date', () => {
    expect(formatTimestamp('not-a-date')).toBe('not-a-date')
  })
})

describe('formatCount', () => {
  it('groups thousands explicitly', () => {
    expect(formatCount(1024)).toBe('1,024')
    expect(formatCount(6)).toBe('6')
  })
})
