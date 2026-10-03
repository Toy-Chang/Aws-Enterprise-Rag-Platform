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

## What is not here yet

- **No infrastructure as code.** Nothing in this repository creates the bucket, the
  domain, the index, the database or the IAM roles. Terraform and a docker-compose stack
  are the next piece of this phase.
- **No queue and no consumer.** Ingestion is driven by the in-process worker polling the
  database. That is correct for a single task and is what the local stack uses. With more
  than one task, two pollers would race for the same document; SQS and a consumer are the
  intended replacement, and they are not written yet. Until then, run exactly one task
  with `APP_INGESTION_WORKER_ENABLED=true` and set it to `false` everywhere else.
- **No authentication.** Every endpoint is open, so the service must not be exposed
  publicly. Cognito is planned and not implemented.
- **No pgvector adapter.** PostgreSQL is used for documents and chunks; the vectors live
  in OpenSearch.
- **No streaming, no caching, no query rewriting.** Unchanged from the earlier phases.

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
  the services, and refuses a configuration that cannot work.

Verified by running the service locally:

- with the AWS vector store configured against a closed port, a query answers `502
  VECTOR_STORE_ERROR` and ingestion records the document as `failed`;
- with `APP_STORAGE_BACKEND=s3` and no bucket, the process exits during startup;
- with the default configuration, upload, ingestion, query, citations and metrics all
  still work.

**Never verified**: any request to a real S3 bucket, a real Bedrock model or a real
OpenSearch domain. There is no AWS account available here. The tests prove the mapping
and the failure handling; only a deployment can prove the mapping matches the service.
