/**
 * PKCE, spelled out.
 *
 * Cognito's hosted UI is a browser redirect, and a browser app cannot keep a secret. PKCE
 * (RFC 7636) is what makes the authorization code safe to hand back to a public client: the
 * app sends the SHA-256 of a random verifier when it starts, and the verifier itself when
 * it exchanges the code. An attacker who intercepts the code — from the URL bar, history,
 * or a referrer header — cannot use it without the verifier, which never left the tab.
 *
 * Everything here is `crypto.getRandomValues` and `crypto.subtle`: no dependency, and no
 * value derived from `Math.random`, which is not a CSPRNG.
 */

const VERIFIER_BYTES = 32

/** Base64url without padding, which is what Cognito (and JOSE generally) expects. */
export function base64UrlEncode(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomBytes(length: number): Uint8Array {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return bytes
}

/**
 * A `code_verifier`: 43 characters from 32 random bytes.
 *
 * RFC 7636 allows 43–128 characters from the unreserved set; base64url of 32 bytes lands
 * at the bottom of that range, which is the strength of a 256-bit random value.
 */
export function createCodeVerifier(): string {
  return base64UrlEncode(randomBytes(VERIFIER_BYTES))
}

/** `code_challenge` = base64url(SHA-256(verifier)), the `S256` method. */
export async function createCodeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64UrlEncode(new Uint8Array(digest))
}

/**
 * The `state` parameter: a second random value, from the same CSPRNG, echoed back by
 * Cognito on the callback. Its only job is to bind the callback to this tab's sign-in
 * attempt, which is what stops a code from another session being dropped into ours.
 */
export function createState(): string {
  return base64UrlEncode(randomBytes(VERIFIER_BYTES))
}
