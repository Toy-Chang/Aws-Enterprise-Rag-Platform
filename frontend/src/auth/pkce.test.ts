/**
 * PKCE: the verifier's shape and the known SHA-256 vector.
 *
 * The vector is the one from RFC 7636 Appendix B. Verifying it here is what turns "we call
 * `crypto.subtle.digest`" into "we compute the value Cognito will compute" — if the encoding
 * were wrong, the hosted UI would reject the exchange and nothing else in these tests would
 * notice.
 */

import { describe, expect, it } from 'vitest'

import { base64UrlEncode, createCodeChallenge, createCodeVerifier, createState } from './pkce'

const RFC_7636_VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
const RFC_7636_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'

/** The unreserved characters base64url is limited to, once padding is stripped. */
const BASE64URL = /^[A-Za-z0-9_-]+$/

describe('base64UrlEncode', () => {
  it('uses the URL-safe alphabet and no padding', () => {
    // 0xfb 0xff encodes to "+/8=" in standard base64: both substitutions and the padding
    // are exercised by this one value.
    expect(base64UrlEncode(new Uint8Array([0xfb, 0xff]))).toBe('-_8')
    expect(base64UrlEncode(new Uint8Array([1, 2, 3]))).toBe('AQID')
  })
})

describe('createCodeVerifier', () => {
  it('is 43–128 characters of the unreserved set', () => {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const verifier = createCodeVerifier()
      expect(verifier.length).toBeGreaterThanOrEqual(43)
      expect(verifier.length).toBeLessThanOrEqual(128)
      expect(verifier).toMatch(BASE64URL)
    }
  })

  it('does not repeat, because it is drawn from the CSPRNG', () => {
    const seen = new Set<string>()
    for (let attempt = 0; attempt < 50; attempt += 1) {
      seen.add(createCodeVerifier())
    }
    expect(seen.size).toBe(50)
  })
})

describe('createCodeChallenge', () => {
  it('matches the RFC 7636 Appendix B vector (S256)', async () => {
    await expect(createCodeChallenge(RFC_7636_VERIFIER)).resolves.toBe(RFC_7636_CHALLENGE)
  })

  it('is the digest of the given verifier, not a constant', async () => {
    const first = await createCodeChallenge('a-verifier-that-is-long-enough-to-be-valid-0001')
    const second = await createCodeChallenge('a-verifier-that-is-long-enough-to-be-valid-0002')
    expect(first).not.toBe(second)
    expect(first).toMatch(BASE64URL)
    // SHA-256 is 32 bytes, which is 43 base64url characters with the padding removed.
    expect(first).toHaveLength(43)
  })
})

describe('createState', () => {
  it('is random per call', () => {
    const seen = new Set<string>()
    for (let attempt = 0; attempt < 50; attempt += 1) {
      const state = createState()
      expect(state).toMatch(BASE64URL)
      seen.add(state)
    }
    expect(seen.size).toBe(50)
  })
})
