# ADR 0007 — AWS adapters behind the existing ports

- **Status:** accepted
- **Phase:** 7
- **Date:** 2026-01-01

## Context

Phases 1 to 6 built the platform against local adapters: documents on the filesystem,
a lexical hashing embedder, and a brute-force in-memory index. Every one of them sits
behind a port (`DocumentStorage`, `EmbeddingModel`, `VectorStore`) so that the AWS
implementations could be added without changing a service. This phase adds them: S3 for
documents, Bedrock for embeddings, OpenSearch for vectors.

The constraint that shapes everything here is that this repository has **no AWS
account**. Whatever is written cannot be exercised against a real S3 bucket, a real
Bedrock model or a real domain. So the goal is not "a deployment that is known to work"
— it is a deployment whose request and response mapping is pinned down by tests, whose
failure modes are explicit, and whose unverified parts are stated where a reader will
see them rather than left to be discovered.

## Decisions

### 1. One adapter per concern, selected by configuration in one module

`app/adapters.py` holds `build_storage`, `build_embedder` and `build_vector_store`. The
composition root calls them; nothing below it knows which implementation it was given.
Each concern is selected independently, so a deployment can move documents to S3 while
embeddings stay local, and the local stack keeps needing no AWS SDK and no credentials.

The alternative — a single "cloud mode" switch — was rejected because the three
concerns have genuinely different migration stories. Moving vectors to OpenSearch is a
bigger step than moving uploaded files to S3, and a deployment should be able to take
them one at a time.

### 2. Every SDK import is deferred, and every adapter accepts an injected client

`boto3` and `opensearchpy` are imported inside client construction, never at module
scope, and each adapter takes an optional `client`. Two things follow.

The mapping is testable without an account: the tests drive the real adapter code
against a stub that records the calls and returns the shape the SDK returns. That is
what pins down "the request carries `dimensions`", "the bulk body has one action pair
per record", "the k-NN query is filtered by knowledge base".

And a missing extra produces an actionable failure rather than an `ImportError` at
import time:

```
the S3 storage adapter needs the AWS SDK: install the 'aws' extra
(pip install -e '.[aws]') or set APP_STORAGE_BACKEND=local
```

### 3. A configuration that cannot work fails while the process starts

`Settings` refuses `storage_backend="s3"` without `s3_bucket`, `vector_store_backend=
"opensearch"` without `opensearch_endpoint`, and half a basic-auth pair. This was
verified by running the service: with `APP_STORAGE_BACKEND=s3` and no bucket it exits
with a validation error naming the missing setting, instead of starting and failing at
the first upload.

Half a pair is refused rather than tolerated because a username without a password
would look configured and silently fall back to SigV4 signing, which fails later, with
an authentication error that says nothing about the real mistake.

### 4. The OpenSearch score is converted, and the distance is not a setting

This is the decision that matters most for correctness. OpenSearch reports a
`cosinesimil` score as `(1 + cos) / 2`: an orthogonal pair is 0.5, not 0.0. The
in-memory adapter returns the cosine itself, and `retrieval_min_score` is a policy
written against that scale — the threshold that decides "the knowledge base does not
cover this" was measured as a cosine (0.1 by default, 0.35 in the evaluation in ADR
0005). Leaving the score unconverted would silently change what "relevant enough" means
depending on which index answered, and a threshold tuned on one backend would be wrong
on the other.

So the adapter converts back (`cosine = 2 * score - 1`), and `space_type` is fixed at
`cosinesimil` in the index mapping rather than exposed: a different distance would need
a different conversion, and making it configurable would make the threshold's meaning
configurable too. A deployment that wants another distance has to change the adapter
and the policy together, deliberately.

### 5. A write waits for the refresh, and a partially failed bulk is a failure

OpenSearch makes a document searchable after a refresh, not when the write returns. The
API reports a document as `ready` when ingestion has finished, so a write refreshes with
`wait_for`: "ready means searchable" is a promise the platform makes and should keep. It
costs latency per batch, and the setting can be relaxed for a bulk rebuild, which is why
it is a constructor argument rather than a constant.

A bulk request answers 200 even when individual actions failed. Treating that as success
would leave a document half-indexed while the API called it ready, so the per-item
result is inspected and a rejection raises.

### 6. Dimensions and finiteness are checked where they are cheapest to check

The adapter refuses a vector whose length is not the index's before sending anything,
which is the same check the in-memory adapter makes. The embedding adapter checks the
model's response against the configured dimension count and refuses non-finite values.

Both exist because of how these mistakes surface otherwise. A vector of the wrong length
is accepted by a store that does not check and fails later, at query time, as a
dimension mismatch inside the index — a long way from the call that caused it. A single
`NaN` is worse: it makes every similarity it participates in `NaN`, and the ranking
becomes meaningless without anything failing.

### 7. Secrets are typed as secrets, and the template carries none

The OpenSearch password is a `SecretStr`, so it cannot be read out of a representation
of the settings. `.env` is ignored by git; `.env.example` documents every setting with
the defaults the platform actually runs with and contains no credentials. The
`.env.example` that this phase adds is the first file in the repository that describes
the whole configuration surface in one place.

### 8. The S3 key space is the filesystem adapter's key space

Both adapters accept a plain relative key and refuse the same inputs: empty, absolute, a
backslash, or a `..` segment. A bucket has no root to escape, so the S3 adapter does not
need the check for safety — it needs it so that a key means the same thing to both
backends. A key that the filesystem adapter rejects and the bucket adapter accepts would
make the two deployments disagree about which object a document is stored as.

### 9. Provider failures are domain errors beside their ports

`EmbeddingFailedError` and `VectorStoreError` are declared next to the ports they belong
to, the way `DocumentStorageError` is declared beside the storage port, and they are
`AppError` subclasses with status 502. An upstream failure is a bad gateway, not an
internal fault of this service, and the distinction is visible in the API contract.

`DocumentStorageError` predated this phase as a bare `Exception`, which meant a bucket
that refused a call reached the caller as `500 INTERNAL_ERROR`. It was brought into line
with the other two, so all three adapters report an unreachable upstream the same way.
This is a small, deliberate change to a committed file: an operator reading a 500 should
be able to trust that something in *this* service is wrong.

This was verified against a real HTTP request: with the vector store pointed at a closed
port, a query answers `502` with code `VECTOR_STORE_ERROR`, and ingestion records the
document as `failed` with the reason attached rather than crashing the worker.

### 10. What this phase does not contain

Stated here so it is not inferred from the directory listing:

- **No queue and no consumer.** Ingestion is still driven by the polling worker reading
  the database, which is correct for one process and is what the local stack uses. The
  SQS queue and its consumer are the next piece of this phase.
- **No authentication.** Every endpoint is open.
- **No Terraform and no docker-compose.** The adapters can be configured by environment
  variables; nothing yet creates the bucket, the domain, the index or the tasks.
- **No pgvector adapter.** The README describes the vector store as "OpenSearch or
  PostgreSQL with pgvector". Only OpenSearch exists. A second implementation of the same
  port would double a surface that cannot be verified here without adding a capability
  the platform does not have yet.

## Consequences

- The AWS path is structurally tested and has never been exercised against a live
  account. A first deployment should expect to fix request details that only a real
  service can reveal — an IAM action, a Serverless mapping option, a model's parameter
  support.
- `rebuild_vector_index` runs at startup and upserts every stored embedding. Against
  OpenSearch that is a real write on every boot, which is acceptable at this scale and
  would not be at a larger one.
- The embedder and the index share `embedding_dimensions`, so they cannot disagree. The
  cost is that changing the embedding model requires re-ingesting the corpus, because
  the stored vectors have the old length. Nothing migrates them.
- The local stack is unchanged: no AWS SDK is imported, and the same tests pass with
  neither `boto3` nor `opensearchpy` installed in a deployment that does not use them.

## Alternatives considered

- **One "cloud" switch for all three adapters.** Rejected; see decision 1.
- **Implementing pgvector as well.** Deferred with the reasoning in decision 10.
- **Fetching documents through `boto3`'s resource API.** Rejected: the client API is
  closer to the wire, which is what these tests are pinning down.
- **Letting `min_score` be interpreted per backend.** Rejected: a threshold that means
  different things in different deployments is not a policy, it is a coincidence.
- **Making `refresh` always `wait_for`.** Rejected as a constant; the rebuild path
  genuinely wants it off, and the default is the honest one for a write during
  ingestion.
- **Skipping dimension validation and letting the index complain.** Rejected; see
  decision 6.
- **A pgvector adapter instead of OpenSearch.** Rejected for now: OpenSearch is the
  managed index the rest of the design assumes, and pgvector would need its own
  extension, schema and migration story.

## Follow-up work

- The SQS queue, its consumer and the Lambda entry point, so ingestion stops depending on
  a process that is running.
- Cognito authentication for the API and the UI.
- Terraform for the bucket, the domain, the index, the database, the tasks and the IAM
  roles, and a docker-compose stack for the whole platform.
- One verification against a real account, recorded in the README, the moment one is
  available.
