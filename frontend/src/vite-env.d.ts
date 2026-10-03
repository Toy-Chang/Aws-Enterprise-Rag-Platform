/// <reference types="vite/client" />

/**
 * The environment the bundle is built with.
 *
 * `VITE_`-prefixed because Vite inlines exactly these into the client bundle. Nothing here
 * is a secret: everything in this file is readable by anyone who loads the page, which is
 * why the app client below is a *public* Cognito client with no secret and the flow is
 * PKCE. A client secret in a browser bundle is not a secret.
 *
 * The Cognito variables are optional on purpose. When the domain or the client id is
 * missing the app runs with authentication off — see `src/auth/config.ts`.
 */
interface ImportMetaEnv {
  /** Base URL for API calls. Empty by default: same origin, proxied by Vite in dev. */
  readonly VITE_API_BASE_URL?: string
  /** Cognito hosted UI host, e.g. `my-app.auth.eu-west-1.amazoncognito.com` (no scheme). */
  readonly VITE_COGNITO_DOMAIN?: string
  /** The app client id. Public by design: a browser client has no secret. */
  readonly VITE_COGNITO_CLIENT_ID?: string
  /** Absolute URL Cognito returns the authorization code to. Defaults to `<origin>/callback`. */
  readonly VITE_COGNITO_REDIRECT_URI?: string
  /** Absolute URL Cognito sends the browser to after sign-out. Defaults to `<origin>/`. */
  readonly VITE_COGNITO_LOGOUT_URI?: string
  /** Space-separated OAuth scopes. Defaults to `openid email profile`. */
  readonly VITE_COGNITO_SCOPES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
