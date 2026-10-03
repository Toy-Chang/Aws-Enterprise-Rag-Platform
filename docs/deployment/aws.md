# Running the platform on AWS

This document describes what the AWS adapters need and how to switch the platform onto
them. It is written from the code and the tests in this repository.

> **None of this has been run against a live AWS account.** There are no credentials in
> this environment and no account to point at. What *is* verified is listed at the end of
> this document, and it is verification by test and by local run, not by deployment.
> Expect to fix details only a real service can reveal — an IAM action, a Serverless
> mapping option, a model's parameter support.

## What the platform needs

Three concerns can be moved to AWS independently. Each is an environment variable.

### Documents: S3

| Setting | Value |
|---|---|
| `APP_STORAGE_BACKEND` | `s3` |
| `APP_S3_BUCKET` | the bucket name (required) |
| `APP_S3_PREFIX` | key prefix, `documents` by default |
| `APP_S3_REGION` | the bucket's region |

Objects are written under `<prefix>/<storage key>`, where the storage key is the
identifier the API already used for the local filesystem (`<knowledge base>/<document>`).
The bucket is not created by the platform.

**IAM**: `s3:PutObject`, `s3:GetObject` and `s3:DeleteObject` on
`arn:aws:s3:::<bucket>/<prefix>/*`. Nothing else is used: there is no listing, no
versioning call and no bucket-level operation.

### Embeddings: Amazon Bedrock

| Setting | Value |
|---|---|
| `APP_EMBEDDING_PROVIDER` | `bedrock` |
| `APP_EMBEDDING_DIMENSIONS` | the vector length to ask the model for |
| `APP_BEDROCK_EMBEDDING_MODEL_ID` | `amazon.titan-embed-text-v2:0` by default |
| `APP_BEDROCK_REGION` | the region to call |

`APP_EMBEDDING_DIMENSIONS` is sent to the model with every request and the response is
checked against it, so the index and the model cannot end up disagreeing. Titan Text
Embeddings V2 supports 1024, 512 and 256; 1024 is the default worth using, and the local
default of 256 does not carry over.

Two consequences worth knowing before switching:

- **One request per chunk.** Titan's embedding API takes one text, so ingesting a
  document with nineteen chunks is nineteen calls. There is no batching in this adapter
  because there is no batch operation to use.
- **Changing the model means re-ingesting.** Stored vectors have the length of the model
  that produced them. Nothing migrates them.

**IAM**: `bedrock:InvokeModel` on the embedding model's ARN (and on the generation
model's ARN if `APP_GENERATION_PROVIDER=bedrock`).

### Vectors: OpenSearch

| Setting | Value |
|---|---|
| `APP_VECTOR_STORE_BACKEND` | `opensearch` |
| `APP_OPENSEARCH_ENDPOINT` | the domain or collection endpoint (required) |
| `APP_OPENSEARCH_INDEX` | index name, `rag-chunks` by default |
| `APP_OPENSEARCH_REGION` | the signing region |
| `APP_OPENSEARCH_SERVERLESS` | `true` for a Serverless collection |
| `APP_OPENSEARCH_VERIFY_CERTS` | leave `true`; `false` logs a warning |
| `APP_OPENSEARCH_USERNAME` / `APP_OPENSEARCH_PASSWORD` | optional, see below |

The index is created on the first write, with a `knn_vector` field sized for
`APP_EMBEDDING_DIMENSIONS`, HNSW, and `cosinesimil` distance. It is not created by
Terraform or by hand.

**Authentication.** With both `APP_OPENSEARCH_USERNAME` and `APP_OPENSEARCH_PASSWORD`
set, requests carry basic authentication. With neither, they are signed with SigV4 using
the credentials the AWS SDK finds; a managed domain is signed with service `es` and a
Serverless collection with `aoss`. Setting only one of the two is refused at startup.

**Serverless differences.** A Serverless collection does not offer the `nmslib` engine,
so the mapping uses `faiss` when `APP_OPENSEARCH_SERVERLESS=true`. Collections also
cannot be reached from outside a VPC, and they need a data access policy rather than the
IAM-only access a managed domain uses for its own API.

**IAM**: `es:ESHttp*` on the domain ARN for a managed domain, or the equivalent data
access policy for a collection.

**Wait for refresh.** Every write uses `refresh=wait_for`, because the API reports a
document as `ready` when ingestion finishes and a document that is not yet searchable
would make that a lie. If a deployment ever rebuilds the whole index, that is the setting
to relax.

### Ingestion work: SQS and a Lambda consumer

With `APP_QUEUE_BACKEND=sqs`, the upload and reprocess endpoints publish a message naming
the knowledge base and the document, and ingestion happens wherever the queue is
consumed. The message carries a version and two identifiers and nothing else: the
document row stays the only source of truth for content, chunking and embeddings.

```
export APP_QUEUE_BACKEND=sqs
export APP_SQS_QUEUE_URL=https://sqs.eu-west-1.amazonaws.com/123456789012/rag-ingestion
export APP_SQS_REGION=eu-west-1
export APP_INGESTION_WORKER_ENABLED=false
```

**Turn the worker off.** The polling worker and a queue consumer both look for documents
waiting to be ingested, so a deployment that runs both ingests the same document twice.
The queue is what lets more than one task run: several API tasks can serve requests while
the consumer is the only thing draining the queue.

**IAM**: `sqs:SendMessage` on the queue ARN for the API task or role.

**The consumer.** `app.aws.handler:handler` is the Lambda entry point and the event source
mapping for the queue is its trigger. It takes a batch, ingests what it can, and answers
with the messages that have to come back:

```json
{"batchItemFailures": [{"itemIdentifier": "8f0d1f4e-..."}]}
```

The function must be configured with **`ReportBatchItemFailures`**, otherwise a batch that
reports a partial failure still has every message deleted. A message is left for retry
when the document does not exist, is still `processing`, the body cannot be read, or the
status cannot be read; it is deleted once the document is `ready` or `failed`, because
that means the outcome was recorded. Give the queue a visibility timeout that comfortably
exceeds one document's ingestion — a document that is still running when the timeout
expires is redelivered and ingested a second time — and a dead-letter queue with a
`maxReceiveCount`, so a message that never becomes valid stops being retried instead of
cycling forever.

**Publishing is not transactional.** The row is committed before the message is published,
so a consumer never sees a message for a document it cannot find, and a crash between the
two commits leaves a document that was never queued. The caller sees `502
QUEUE_UNAVAILABLE` rather than a success it cannot act on, and `reprocess` is the recovery
path.

### Identity: Cognito

| Setting | Value |
|---|---|
| `APP_AUTH_BACKEND` | `cognito` (the default in the Terraform stack; `none` is refused in production) |
| `APP_COGNITO_USER_POOL_ID` | the pool id, for example `eu-west-1_AbCdEfGhI` (required) |
| `APP_COGNITO_CLIENT_ID` | the app client id (required) |
| `APP_COGNITO_REGION` | region of the pool, used to build the issuer |
| `APP_COGNITO_ISSUER` | overrides the derived issuer, for a pool in another account |
| `APP_COGNITO_JWKS_CACHE_SECONDS` | how long the key document is cached, one hour by default |
| `APP_AUTH_LEEWAY_SECONDS` | tolerated clock skew, 60 seconds by default |

The API verifies the token itself and caches the pool's key document, so an authenticated
request costs no call to Cognito. Roles are the pool's groups: `viewer`, `editor`, `admin`,
ordered, with `admin` satisfying everything below it. A route that needs no token is
`/health`, `/health/ready` and `/`; everything under `/api` needs one. The full flow, the
role matrix and the two failure modes a first deployment hits are in
[cognito.md](./cognito.md).

### The database URL

| Setting | Value |
|---|---|
| `APP_DATABASE_URL` | the assembled URL. An ECS task definition resolves it from Secrets Manager; set it directly in a local run |
| `APP_DATABASE_SECRET_ARN` | only for the Lambda consumer, which cannot use `valueFrom` and reads the secret's `url` entry at cold start |

## Running it

```bash
# Documents on S3, embeddings from Bedrock, vectors in OpenSearch.
export APP_STORAGE_BACKEND=s3
export APP_S3_BUCKET=my-rag-documents
export APP_S3_REGION=eu-west-1

export APP_EMBEDDING_PROVIDER=bedrock
export APP_EMBEDDING_DIMENSIONS=1024
export APP_BEDROCK_REGION=eu-west-1

export APP_VECTOR_STORE_BACKEND=opensearch
export APP_OPENSEARCH_ENDPOINT=https://search-example.eu-west-1.es.amazonaws.com
export APP_OPENSEARCH_REGION=eu-west-1

# The database is still the source of truth for documents and chunks. Point it at RDS or
# Aurora PostgreSQL; SQLite is a single-process store and is not a deployment target.
export APP_DATABASE_URL=postgresql+psycopg://user:password@host:5432/rag

# Answers quoted from the retrieved passages. Set generation to `bedrock` to generate
# them instead, which needs model access for the generation model as well.
export APP_GENERATION_PROVIDER=local

.venv/bin/python -m app
```

A configuration that cannot work stops the process while it starts, with a message
naming the missing setting, rather than starting and failing at the first upload:

```
Value error, s3_bucket is required when storage_backend is 's3'
```

### Checking a deployment

1. `GET /health` and `GET /health/ready` — the service and the database.
2. `POST /api/v1/knowledge-bases`, then upload a document and poll it until `ready`. A
   document that fails is reported as `failed` with the reason.
3. `POST /api/v1/knowledge-bases/{id}/query` — an answer with citations, or
   `insufficient_evidence`.
4. `GET /api/v1/metrics` — counters and per-stage latency for what has happened so far.

When a dependency is unreachable, the failure is reported as what it is rather than as a
crash:

| Situation | Response |
|---|---|
| The index cannot be reached or read | `502 VECTOR_STORE_ERROR` |
| The embedding model cannot be reached | `502 EMBEDDING_FAILED` |
| The answer model cannot be reached | `502 GENERATION_FAILED` |
| The bucket refuses a call or the object is missing | `502 STORAGE_ERROR` on upload, or the document `failed` during ingestion |
| The queue refuses the message | `502 QUEUE_UNAVAILABLE` on upload and reprocess; the document stays `pending` |
| The token is missing, malformed or expired | `401 UNAUTHENTICATED` with `WWW-Authenticate: Bearer` |
| The caller's group is below the route's requirement | `403 FORBIDDEN`, with `required_roles` and `held_roles` in `details` |
| The pool's key document cannot be fetched or parsed | `502 AUTH_UNAVAILABLE` (not a 401: the caller's token may be fine) |
| The consumer cannot read its database secret at cold start | `502 SECRET_UNAVAILABLE`, the invocation fails, the error alarm fires |

## What is not here yet

- **A deployment that has ever run.** Every resource this document configures is created
  by `infrastructure/terraform` — network, bucket, database, search domain, queue, roles,
  Cognito pool, load balancer, ECS services and the Lambda consumer — but `terraform
  plan` and `terraform apply` have never been executed here, and no AWS resource has ever
  been created by this repository. See [terraform.md](./terraform.md).
- **A live identity provider.** The verifier's cryptographic path is tested against
  locally generated keys; no user pool exists and no real token has been verified. See
  [cognito.md](./cognito.md).
- **No pgvector adapter.** PostgreSQL is used for documents and chunks; the vectors live
  in OpenSearch.
- **No migrations, no pgvector failover, no streaming, no caching, no query rewriting,
  no rate limiting.** Unchanged from the earlier phases.

## What is verified, and how

Verified by `pytest` against injected stub clients (which is what pins the request and
response mapping):

- the S3 request carries the bucket, the prefixed key and the body; a missing object, a
  denied call and a network failure all become a `502 STORAGE_ERROR`; the keys the
  filesystem adapter refuses are refused here too;
- the Bedrock request carries `inputText`, `dimensions` and `normalize`; a response of
  the wrong length, a non-finite value, a malformed payload and an empty text are all
  refused with `EMBEDDING_FAILED`; an empty batch makes no request;
- the OpenSearch mapping is created once with the right dimension, distance and engine;
  the bulk body has one action pair per record and a partially rejected bulk raises; the
  k-NN query is filtered by knowledge base and bounded by `top_k`; the score is converted
  from `(1 + cos) / 2` back to a cosine; a missing index reads as an empty corpus rather
  than a failure;
- the composition root assembles the AWS adapters from configuration and hands them to
  the services, and refuses a configuration that cannot work;
- the SQS request carries the queue URL and a body that the consumer reads back as the
  same message; a refused send becomes `502 QUEUE_UNAVAILABLE` with the SDK error as its
  cause; the boto3 record shape and the Lambda event shape both normalise to the same
  message;
- a batch reports exactly the messages that have to come back: `ready` and `failed` are
  handled, and an unknown document, a document still `pending`, an unreadable body and a
  status that could not be read are all deferred;
- an upload commits the document before it publishes, which the HTTP tests assert by
  reading the row through a second connection at publish time.

Verified by running the service locally:

- with the AWS vector store configured against a closed port, a query answers `502
  VECTOR_STORE_ERROR` and ingestion records the document as `failed`;
- with `APP_STORAGE_BACKEND=s3` and no bucket, the process exits during startup;
- with `APP_QUEUE_BACKEND=sqs` and an unreachable queue, an upload answers `502
  QUEUE_UNAVAILABLE` with the document left `pending`;
- the Lambda handler was run in a separate process against the database the API had
  written to: it ingested the document the API had queued, reported
  `{"batchItemFailures": []}`, and the API then reported the document as `ready` with 16
  chunks. The same message delivered twice re-ingested it without leaving anything
  behind. An unknown document and a malformed body each came back as a batch item
  failure;
- with the default configuration, upload, ingestion, query, citations and metrics all
  still work.

Verified by `pytest` for authentication and authorization:

- the role scale: a higher role satisfies a lower requirement, an unknown group is not a
  role, a `403` names both the required and the held roles;
- the Cognito verifier against locally generated RSA keys and a signed JWKS document: a
  valid access token and a valid ID token, an expired token and one inside the leeway, a
  wrong issuer, a token issued for another application, a refresh token, a hand-crafted
  `alg=none` token, an HS256 token signed with the public key, a tampered payload, an
  unknown key id with the rate-limited refresh, the cache lifespan under a fake clock, an
  unreachable key document, a document that is not JSON, one that is not an object, and a
  key that cannot be parsed;
- over HTTP: `401` with the challenge header and the standard envelope for a missing,
  malformed or unknown token; the viewer/editor/admin matrix in both directions; the role
  check happening before body validation; the platform probes staying public; and a sweep
  of the OpenAPI document asserting that every path under `/api` answers `401` without a
  token.

Verified by running the tools that need no account:

- `terraform init -backend=false`, `terraform validate` and `terraform fmt -check
  -recursive` pass for the whole root module and all nine modules;
- `docker compose config` and `docker compose --profile opensearch config` resolve.

**Never verified**: any request to a real S3 bucket, a real Bedrock model, a real
OpenSearch domain, a real SQS queue or a real Cognito user pool. There is no AWS account
available here. A real `send_message` has never been made, the event source mapping has
never been created, no Lambda has ever been invoked by SQS, no image has ever been pushed
to ECR, `terraform plan` and `apply` have never run, and no container has ever been built
or started. The tests prove the mapping and the failure handling; only a deployment can
prove the mapping matches the service.
