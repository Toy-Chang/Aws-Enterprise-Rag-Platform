# ADR 0008 — Authentication with Cognito, authorization by group

Status: accepted (Phase 7).

## Context

Every endpoint was open. That was a deliberate Phase 1–6 property: the local stack needed
no identity provider, and an open API made the retrieval pipeline reviewable without a
login. It stopped being acceptable at the point the platform could be deployed, because
the corpus is the asset: an open API means an open corpus, and the evaluation endpoint is
the most expensive request in the system by a wide margin.

Three constraints shaped the design.

1. **The identity provider is not the authorization model.** Cognito can express groups,
   and groups are what a person is a member of. What a *route* requires is a property of
   the application, and it has to be readable where the route is declared, without a
   round trip to AWS and without duplicating a policy document in the infrastructure.
2. **Local development, CI and the container stack must keep working with no identity
   provider at all.** A platform whose tests need a user pool is a platform nobody runs.
3. **Verification has to be real, and testable without an account.** A token check that is
   only exercised against a live pool is a token check that is never exercised.

## Decisions

### 1. A `TokenVerifier` port, and the same ports-and-adapters shape as everything else

`TokenVerifier.verify(token) -> Principal` is a `runtime_checkable` `Protocol`, like
`DocumentStorage`, `EmbeddingModel`, `VectorStore`, `AnswerModel` and `DocumentQueue`.
`AnonymousTokenVerifier` returns an unauthenticated principal that holds every role;
`CognitoTokenVerifier` verifies a real token. The composition root picks one from
`APP_AUTH_BACKEND`, and no route, service or test needs to know which.

The anonymous verifier is not a bypass: the principal it returns has
`authenticated = False`, and the settings refuse `auth_backend = "none"` when
`environment == "production"`. An open API is a local convenience, not a deployment mode.

### 2. Roles are an ordered scale, not a set of permissions

`ROLE_ORDER = (viewer, editor, admin)`. A higher role satisfies a lower requirement, so a
route asks for the *lowest* role that may call it and the policy reads as one line:
`require_roles(EDITOR)`. A set of permissions would mean a role's meaning is distributed
across every route that names it; an ordered scale means adding a route cannot silently
widen an existing role.

Unknown groups in a token are dropped rather than mapped. A pool will accumulate groups
for unrelated purposes, and a token that carries `aws-admins` must not be an admin here
because a string happened to match.

### 3. Fail closed at the router, elevate per route

The baseline dependency sits on the API router:

```python
api_router = APIRouter(dependencies=[Depends(require_roles(VIEWER))])
```

A new router added under it is authenticated by default; forgetting to protect a route
produces a 403, not an open endpoint. Elevation is then explicit and local:
`POST /knowledge-bases` and document upload need `editor`, deleting a knowledge base and
running an evaluation need `admin`. A test sweeps the OpenAPI document and asserts that
every path under `/api` answers `401` without a token, which is what keeps the baseline
honest as routers are added.

`/health`, `/health/ready` and `/` stay public. A load balancer has to be able to ask
whether a task is alive without holding a token, and those three endpoints expose nothing
but liveness and a service name.

### 4. The token is verified locally, against the pool's published key set

The verifier fetches `/.well-known/jwks.json`, caches it for
`APP_COGNITO_JWKS_CACHE_SECONDS` (default one hour), and refreshes it when a token names a
key id it has not seen — rate limited to one refresh per 30 seconds, because the key id
comes from the caller and an unknown one must not become a way to make the service fetch
on every request.

The checks, in order: the algorithm is exactly `RS256` (a token that names `none`, or that
tries HMAC with the public key as the shared secret, is refused *before* any key lookup);
the signature verifies against the key the token names; `iss` is exactly the configured
issuer; `token_use` is `access` or `id` (a refresh token can mint new tokens and must not
be accepted as a credential); the client is this application — `client_id` for an access
token, `aud` for an ID token, because Cognito puts it in different claims for the two; and
`exp`/`iat`/`iss`/`sub` exist. Clock skew of `APP_AUTH_LEEWAY_SECONDS` (default 60) is
tolerated, because a service whose clock is a second behind the pool would otherwise
reject tokens the pool still considers valid.

The failure taxonomy is deliberate. A bad token is `401 UNAUTHENTICATED` with a
`WWW-Authenticate: Bearer` challenge, and the client should sign in again. An unreachable
or unparseable key document is `502 AUTH_UNAVAILABLE`: the caller's token may be perfectly
good, and telling it to sign in again would send it to fix something that is not broken.

### 5. The browser is a public client: PKCE, no secret

The frontend uses the authorization-code flow with PKCE (`S256`) against the hosted UI and
holds no client secret — a secret shipped in a JavaScript bundle is not a secret, and a
Cognito app client that generates one cannot complete this flow from a browser at all. The
session lives in `sessionStorage`: a token that outlives the tab outlives the user's
attention. The API answers `401` when the token is missing or invalid, and the client
clears the session and sends the user to sign in rather than rendering a broken page.

Authentication is off in the frontend when `VITE_COGNITO_DOMAIN` is absent. That branch is
explicit and documented rather than a crash, because the same bundle runs in the local
stack where there is no provider.

### 6. What this does not claim

No user pool has ever been created, no hosted UI has ever been visited, and no live token
has ever been verified. What *is* verified: the verifier's real cryptographic path is
covered by tests that generate an RSA key, publish it as a JWKS document and sign real
tokens — valid access and ID tokens, an expired token and one inside the leeway, a wrong
issuer, a token issued for another application, a refresh token, a hand-crafted `alg=none`
token, an HS256 token signed with the public key, a tampered payload, an unknown key id
with the rate-limited refresh, cache expiry under a fake clock, an unreachable key
document, and a key document that is not a document. Rotating keys, `auth_time` policies
and MFA enforcement are Cognito configuration; the platform does not test them.

## Consequences

- The API has no session store and no server-side revocation: a token is valid until it
  expires. Access tokens are short lived (60 minutes in the Terraform module) for exactly
  that reason, and `enable_token_revocation` is on for the app client.
- Every route now has an owner: the baseline is `viewer`, so a route that should be public
  has to say so, and a route that mutates has to elevate. That is more code than an open
  API, and it is the code that makes a deployment defensible.
- The Cognito dependency is optional: `pip install ".[auth]"` brings PyJWT and
  cryptography, and a deployment with `auth_backend = none` never imports either. The
  base install stays small enough to run offline.
- The role model is coarse. Three roles cannot express "may upload to this knowledge base
  but not that one". Per-knowledge-base ownership is a data-model change.
- The suite grew by about 90 tests: the port and the policy, the verifier against real
  signatures, the HTTP matrix, and the fail-closed sweep. A security property that is not
  tested is a security property that regresses quietly.

## Alternatives considered

- **An API gateway authorizer, or ALB authentication.** Moves the decision into
  infrastructure and out of the repository: the same route would then be protected in a
  deployment and unprotected when the app runs locally, and the role requirement would be
  invisible to anyone reading the router. Rejected: the authorization model belongs with
  the routes it describes.
- **Verifying tokens with `amazon-cognito-identity-js` in the browser only.** The browser
  cannot be the enforcement point. Decoding a token in the client is for display; the
  server has to verify the signature.
- **A session cookie and a server-side session table.** Would need a session store, a CSRF
  story and a cookie policy, and would make the API stateful in a way the rest of the
  design avoids. A bearer token verified locally needs none of it.
- **A permissions table rather than three roles.** More expressive, and premature: with
  one team, three roles is the whole policy. The ordered scale is the part that would
  survive a change to a finer model.
- **Rejecting all clock skew.** Simpler by one setting, and it produces an
  authentication failure that is indistinguishable from a bad token during a deploy.

## Follow-up work

- Per-knowledge-base authorization (an owner column and a scoped requirement) if the
  platform is ever used by more than one team.
- Rate limiting and request quotas. The evaluation endpoint is `admin`-only now, which
  removes the obvious abuse, and it is still the most expensive request in the system.
- An audit trail of who read which corpus, which the structured logs almost provide: every
  request already carries a request id, and the principal's subject is not yet logged.
- MFA enforcement (`mfa_configuration = "ON"`) once there are real users to enrol.
