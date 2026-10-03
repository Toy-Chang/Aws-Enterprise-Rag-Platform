# Cognito authentication

This document describes the identity provider the Terraform stack creates, the sign-in flow
the browser runs, and how a token becomes a principal in the API. It is written from the
code in `infrastructure/terraform/modules/auth/`, `backend/app/aws/cognito_auth.py`,
`backend/app/api/` and `frontend/src/auth/`.

> **No user pool has ever existed.** No pool has been created, no hosted UI has been
> visited, no token has ever been issued by Cognito, and no sign-in flow has been exercised
> against a live pool. What *is* verified is the verifier's cryptographic path against
> locally generated keys, and the API's authorization behaviour against injected
> principals. Both are listed at the end. Every command in this document that would create
> or read a pool is marked as not executed.

## What the `auth` module creates

`name_prefix` is `<project>-<environment>`, so with the defaults the pool is
`rag-platform-production-users`.

| Resource | Value | Why it is set that way |
| --- | --- | --- |
| `aws_cognito_user_pool` | Name `<prefix>-users`, `username_attributes = ["email"]`, `allow_admin_create_user_only = true` | The address is the identifier and an administrator creates every account. Self-service sign-up would let anyone with an email address create a principal, and the pool would be the only thing between them and the corpus |
| | `mfa_configuration = "OPTIONAL"`, software token TOTP enabled | MFA is available and not required. Nothing in the platform tests or enforces it |
| | Password policy: 12 characters minimum, and lower-case, upper-case, number and symbol required | Cognito's own policy, applied at sign-in |
| | `auto_verified_attributes = ["email"]`, recovery by verified email | |
| | Required, mutable `email` attribute | |
| `aws_cognito_user_pool_client` | `<prefix>-web`, `generate_secret = false` | A public client. A secret shipped in a JavaScript bundle is not a secret, so PKCE is what protects the code instead |
| | `allowed_oauth_flows = ["code"]`, scopes `openid email profile`, provider `COGNITO` | Authorization code only: the implicit flow puts tokens in a URL |
| | `explicit_auth_flows`: `ALLOW_USER_SRP_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH` | The hosted UI signs in with SRP; the app refreshes with the refresh token |
| | Access token 60 minutes, ID token 60 minutes, refresh token 30 days | An access token cannot be revoked once issued, so it is short lived; the refresh token is what keeps a session usable |
| | `enable_token_revocation = true` | A signed-out token stays dead instead of remaining valid until it expires |
| | `prevent_user_existence_errors = "ENABLED"` | Answering "user does not exist" differently from "wrong password" tells an attacker which addresses are real |
| | `read_attributes = ["email", "email_verified"]`, `write_attributes = ["email"]` | Enough to sign in and read the address, nothing else |
| `aws_cognito_user_pool_domain` | `var.domain_prefix`, derived from the prefix when the variable is empty | The hosted UI. Cognito requires the prefix to be unique across the region, so a collision is a variable change and not a code change |
| `aws_cognito_user_group` | One per entry of `groups`: `viewer`, `editor`, `admin`, with precedence 30, 20 and 10 | The groups are the roles. Precedence only matters when a group maps to an IAM role in an identity pool, which this stack does not use, but the order is stated so an admin outranks an editor if that ever changes |

The module validates that at least one group exists, that at least one callback URL is
given, and that every group is one of the three the application knows. The root module's
`auth_groups` variable carries the same validation.

## The sign-in flow, end to end

Authorization code with PKCE (RFC 7636), no client secret, `S256`.

1. **The app starts the flow.** `signIn` in `frontend/src/auth/AuthContext.tsx` generates a
   `code_verifier` (32 random bytes from `crypto.getRandomValues`, base64url-encoded to 43
   characters) and a `state` from the same CSPRNG, computes
   `code_challenge = base64url(SHA-256(verifier))`, and stores `{state, codeVerifier,
   returnTo}` in `sessionStorage`. The callback is a full page load, so an in-memory
   verifier would be gone by the time the code comes back.
2. **The browser is sent to the hosted UI.** `buildAuthorizeUrl` builds
   `https://<domain>/oauth2/authorize` with `response_type=code`, `client_id`,
   `redirect_uri`, `scope`, `state`, `code_challenge` and `code_challenge_method=S256`.
   `login_hint` is added when the sign-in follows a sign-out.
3. **Cognito authenticates and redirects back** to the registered `redirect_uri` with
   `?code=...&state=...`, or with `?error=...` when it refuses.
4. **The app checks `state` first, then exchanges the code.** The pending authorization is
   read and cleared *before* the comparison, so a callback whose state does not match
   cannot leave a usable verifier behind for a replayed code. The exchange is a POST to
   `https://<domain>/oauth2/token` with `grant_type=authorization_code`, `client_id`,
   `code`, `redirect_uri` and `code_verifier`. There is no `client_secret` in the request
   and none in the bundle.
5. **The session is stored** (`sessionStorage`, tab-scoped) and every API call carries
   `Authorization: Bearer <access token>`. Sixty seconds before `exp` the client exchanges
   the refresh token for a new access token rather than racing expiry.
6. **Sign-out** clears the session and redirects to `https://<domain>/logout` with
   `client_id` and `logout_uri`, which ends Cognito's own session cookie as well.

The API is never part of this exchange. It only verifies what arrives.

### What the browser actually needs for this to work

Two URLs have to be registered on the app client before any of it completes:

| Value | Where it comes from | In the pool |
| --- | --- | --- |
| `redirect_uri` | `VITE_COGNITO_REDIRECT_URI`, default `<window.location.origin>/callback` | Has to be listed in `auth_callback_urls` |
| `logout_uri` | `VITE_COGNITO_LOGOUT_URI`, default `<window.location.origin>/` | Has to be listed in `auth_logout_urls` |

The variable defaults are `["http://localhost:5173/callback"]` and
`["http://localhost:5173/"]`, which is the dev server and not a deployment. In a deployed
stack both lists have to name the host the load balancer serves — see
`docs/deployment/terraform.md` for why that is a second apply.

## How a token becomes a principal

`app.aws.cognito_auth.CognitoTokenVerifier` runs against the pool's published JWKS. It
fetches `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>/.well-known/jwks.json`
over HTTPS with `urllib` — no boto3, no AWS credentials, only the `auth` extra for JWT
parsing and RSA verification. It is constructed by `app.adapters.build_token_verifier` only
when `auth_backend` is `cognito`.

In order, for every request:

| Step | Check | Failure |
| --- | --- | --- |
| 1 | The `Authorization` header is present and uses the `Bearer` scheme | `401 UNAUTHENTICATED` with `WWW-Authenticate: Bearer realm="api"` |
| 2 | The token parses as a JWT and its header names a key | `401 UNAUTHENTICATED` |
| 3 | `alg` is `RS256` — checked before any key is looked up | `401`. This is what refuses the confusion attack: an `HS256` token "signed" with the pool's public key as if it were a shared secret must never verify, and an unsigned token is refused even earlier |
| 4 | The signature verifies against the key named by `kid` | `401`, or `502 AUTH_UNAVAILABLE` when the pool's key document cannot be reached or is unusable |
| 5 | `iss` equals the pool's issuer | `401` |
| 6 | `exp`, `iat` and `sub` are present, and `exp` is in the future within `APP_AUTH_LEEWAY_SECONDS` | `401` |
| 7 | `token_use` is `access` or `id`, never `refresh` | `401` |
| 8 | The token names this application: `client_id` for an access token, `aud` for an ID token | `401`. The library's own audience check is off, because a Cognito access token carries no `aud` at all |
| 9 | `cognito:groups` becomes the principal's groups, and the subject, user name and scopes come from the claims | No `cognito:groups` means no roles, and every role-gated route then answers `403` |

The issuer is derived from `APP_COGNITO_USER_POOL_ID` and `APP_COGNITO_REGION`, or taken
verbatim from `APP_COGNITO_ISSUER` when it is set. Keys are cached for
`APP_COGNITO_JWKS_CACHE_SECONDS`. An unknown `kid` triggers one refresh, rate limited to
one per 30 seconds, which is what makes the first request after a rotation work without
letting a caller turn every request into an outbound fetch.

An unreachable key set is `502 AUTH_UNAVAILABLE`, not `401`: telling a caller with a
perfectly good token to go and get a new one would be the wrong instruction.

## The role matrix

A role is a Cognito group. The three are ordered, and a higher role satisfies a requirement
for a lower one, so `admin` can do everything `editor` can and `editor` everything
`viewer` can. A group the platform does not know is ignored.

| Role | May | Endpoints |
| --- | --- | --- |
| `viewer` | Read | Every route under `/api/v1`: list and get knowledge bases, list documents, read document metadata and chunks, query, read metrics |
| `editor` | Everything a viewer may, plus change the corpus | `POST /api/v1/knowledge-bases`, `POST`, `DELETE` and reprocess on `/api/v1/knowledge-bases/{id}/documents` |
| `admin` | Everything an editor may, plus change the platform itself | `DELETE /api/v1/knowledge-bases/{id}`, `POST /api/v1/evaluations` |

Where that is enforced:

- `app/api/router.py` mounts the versioned router with a baseline dependency of
  `require_roles(VIEWER)`. A newly added route is protected before anyone remembers to
  protect it; a route that changes something declares a stricter requirement of its own.
- `app/api/deps.py` defines `ViewerDep`, `EditorDep` and `AdminDep`, and `authorize` raises
  `403 FORBIDDEN` with `required_roles` and `held_roles` in the error details.
- Health probes (`/health`, `/health/ready`) and service metadata (`/`) are outside the
  versioned prefix and stay public, because a platform probe cannot carry a token.

The frontend mirrors the same ordering in `frontend/src/auth/config.ts` only to avoid
offering a button the server would refuse. The server remains the authority.

## The first user

Every command below is **not executed here**. There is no pool and no AWS credentials in
this environment, so `<user-pool-id>` and `<email>` are placeholders for values a real
deployment would have.

```bash
POOL_ID=$(terraform -chdir=infrastructure/terraform output -raw cognito_user_pool_id)

# 1. Create the account. Sign-up is admin-only, so this is the only way in. Cognito emails
#    a temporary password; the user is asked to change it at first sign-in.
aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username '<email>' \
  --user-attributes Name=email,Value='<email>' Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL

# 2. Put the account in a group. Without a group the token carries no `cognito:groups`
#    claim, the principal holds no role and every API route answers 403.
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$POOL_ID" --username '<email>' --group-name viewer

# For an operator who has to create and delete knowledge bases and run evaluations:
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$POOL_ID" --username '<email>' --group-name admin

# 3. Check what the account holds. `cognito:groups` in the next token is the answer.
aws cognito-idp admin-list-groups-for-user --user-pool-id "$POOL_ID" --username '<email>'

# 4. The hosted UI URL, for a manual sign-in test. The domain prefix is
#    `<project>-<environment>-auth` unless auth_domain_prefix overrides it.
#    https://<domain-prefix>.auth.<region>.amazoncognito.com/login?client_id=<client-id>&response_type=code&scope=openid+email+profile&redirect_uri=<registered-callback>
```

A group change only appears in a token issued *after* it, and an access token lives 60
minutes. A user added to a group while signed in keeps the old roles until the token is
refreshed or the session is restarted.

## Settings the API reads

All of these are `APP_`-prefixed settings in `backend/app/core/config.py`, and the
Terraform root module sets the first four on both the API task and the ingestion function
through `local.app_environment`. The rest keep their defaults unless
`terraform.tfvars` overrides them, because Terraform does not pass them at all.

| Setting | Terraform value | Meaning |
| --- | --- | --- |
| `APP_AUTH_BACKEND` | `cognito` | `none` treats every request as a fully privileged anonymous principal. It is **refused** when `APP_ENVIRONMENT=production`, which is why a deployment cannot accidentally run open |
| `APP_COGNITO_USER_POOL_ID` | `cognito_user_pool_id` output | The pool; the issuer is derived from it and the region |
| `APP_COGNITO_CLIENT_ID` | `cognito_client_id` output | The app client a token has to name. Required, because without it a token issued for any other application in the pool would be accepted |
| `APP_COGNITO_REGION` | `var.region` | Used to derive the issuer when no explicit one is set |
| `APP_COGNITO_ISSUER` | not set | Overrides the derived issuer. Only needed for a non-standard domain |
| `APP_COGNITO_JWKS_CACHE_SECONDS` | not set (default `3600`) | How long the key document is reused before it is fetched again |
| `APP_AUTH_LEEWAY_SECONDS` | not set (default `60`) | Clock skew tolerated when checking `exp` |

`auth_backend=cognito` without a pool id (or an explicit issuer) or without a client id
stops the process at startup with a message naming the missing setting, rather than
starting and answering `401` to everything.

The frontend reads a different family, because `VITE_` values are compiled into the bundle
and are public:

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_COGNITO_DOMAIN` | empty | Hosted UI host, no scheme. **Empty means authentication is off**: no redirect, no bearer header, no route guard |
| `VITE_COGNITO_CLIENT_ID` | empty | The public app client id; also has to be non-empty for authentication to be on |
| `VITE_COGNITO_REDIRECT_URI` | `<origin>/callback` | Must equal a registered callback URL, exactly |
| `VITE_COGNITO_LOGOUT_URI` | `<origin>/` | Must equal a registered logout URL, exactly |
| `VITE_COGNITO_SCOPES` | `openid email profile` | Space-separated |

Authentication is on only when **both** the domain and the client id are set. That is not
a fallback for a broken build: the local stack and the container stack have no pool to
point at, and a UI that redirects to a domain it was never given is unusable. Compose
deliberately does not forward the `APP_AUTH_*` / `APP_COGNITO_*` family, so a half-wired
identity provider is not reachable from `.env`.

The client id and the hosted UI domain are public values. The client secret does not exist,
which is the point of the public client plus PKCE.

## The two failure modes a deployment hits first

Both are configuration, and they look different from the outside.

### Callback URL mismatch — Cognito refuses before the application is reached

The address the browser is sent back to is compared with the registered list, and a value
that is not listed is refused. Cognito renders its own error page; the application is never
reached, so there is nothing in the API log and nothing in the browser console. The
symptom is a hosted UI error page naming `redirect_mismatch` (or, for sign-out,
`logout_uri` not allowed), and the URL bar still on the `amazoncognito.com` domain.

Causes worth checking in order: the deployed host is not in `auth_callback_urls`; the
scheme is `http` where the app sends `https`; a trailing slash or a different port; a
`VITE_COGNITO_REDIRECT_URI` that was overridden and does not match the variable; or a
frontend rebuilt with the new value but the pool not applied again.

### Wrong client id — the app is reached and the API refuses

The sign-in completes and the app holds tokens, but every API call answers
`401 UNAUTHENTICATED`. The server log names the reason: the verifier's message for step 8
is literally *"The access token was issued for another application."* — hence
`another application` in the log. The token itself is valid; it was issued for a different
app client in the same pool.

Causes: `APP_COGNITO_CLIENT_ID` set to an older client's id, or the frontend built against
one pool and the API configured with another.

How to tell them apart in one line: **a callback mismatch never reaches the API and shows a
Cognito error page; a client-id mismatch reaches the API and shows an application `401`.**
`curl` the API with the token and read the `code` in the error envelope — `UNAUTHENTICATED`
is the application's answer, and no envelope at all means the request never got there.

| Symptom | Where it stops | First thing to check |
| --- | --- | --- |
| Cognito error page, `redirect_mismatch` | Cognito, before the app | `auth_callback_urls` versus `VITE_COGNITO_REDIRECT_URI` |
| `401 UNAUTHENTICATED`, server log says another application | The API verifier | `APP_COGNITO_CLIENT_ID` versus `VITE_COGNITO_CLIENT_ID` |
| Cognito error page, `invalid_scope` or `unauthorized_client` | Cognito | `VITE_COGNITO_SCOPES` and whether the client has the code flow enabled |
| `403 FORBIDDEN` with `held_roles: []` | The API authorizer | The user is in no group; a group change needs a new token |
| `502 AUTH_UNAVAILABLE` | The API verifier | The JWKS URL is unreachable from inside the VPC |

A note on the last one: the API tasks run in private subnets and reach the pool's key
document over the NAT gateway, so a VPC with no working egress produces
`502 AUTH_UNAVAILABLE` on every request rather than a `401`.

### One gap in the frontend routing

`frontend/src/features/auth/LoginPage.tsx` and `CallbackPage.tsx` exist, and
`AuthContext` sets the redirect to `/login` and reads the code on `/callback`. Neither page
is registered in `frontend/src/App.tsx`, whose catch-all route sends an unknown path to
`/`. So a build with `VITE_COGNITO_DOMAIN` and `VITE_COGNITO_CLIENT_ID` set would send the
browser to the hosted UI and then land the callback on the catch-all instead of the
exchange. The backend half of this document — the verifier, the claims and the role matrix
— is complete and tested; the browser round trip is not wired up in the tree as it stands.
`RequireAuth` renders the sign-in card inside the app, so a reader should not assume the
pages are reachable because the files are present.

## What is verified, and how

Verified by `pytest`, against RSA keys and a JWKS document generated in the test process —
no network, no pool:

- the verifier satisfies the `TokenVerifier` port, and the issuer and key document are
  derived from the pool and the region, or honoured verbatim when given explicitly;
- a valid access token and a valid ID token each become a principal with the right subject,
  user name, groups and scopes; groups come from `cognito:groups` only, a single group given
  as a string is read, and a token without groups has no roles;
- refused: no token, an expired token, a token from another issuer, an access or ID token
  for another application, a refresh token, a token with no expiry, a tampered payload,
  an unsigned token (refused **before any key is looked up**), an `HS256` token signed with
  the pool's public key, a token without a key identifier, and garbage;
- clock skew inside `APP_AUTH_LEEWAY_SECONDS` is tolerated;
- key handling: an unknown key is refused after exactly one refresh, a rotation is picked
  up, the miss refresh is rate limited, the document is cached, refreshed after its
  lifespan and can be uncached, and an unreachable, non-JSON, list-shaped or unparseable
  key document is `502 AUTH_UNAVAILABLE` rather than a crash;
- at the HTTP layer, against an injected verifier: a request with no token is challenged,
  a malformed `Authorization` header is refused, and the group-to-role mapping decides —
  a viewer reads, a viewer cannot create a knowledge base, an editor can, deleting needs an
  admin, uploading a document needs an editor, the role is checked before the payload is
  parsed, metrics need a token, the health probes stay public, and a sweep of every route
  under `/api/v1` proves each one requires authentication.

**Never verified**: any interaction with a real Cognito user pool. No pool, no app client,
no hosted UI domain and no group has ever been created; no real token has ever been
verified; the authorization-code exchange, the refresh, the hosted UI redirect and the
`/logout` call have never been executed against Cognito; MFA enforcement, `auth_time`
policy and key rotation timing are Cognito configuration that this platform does not test.
The commands in "The first user" are written from the AWS CLI's interface and have not been
run.
