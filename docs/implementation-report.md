# Implementation report

What was built, what was actually run, and what was not. This document is a summary of
evidence that lives in full in [README.md](../README.md#测试与验证--testing--verification),
[deployment/aws.md](./deployment/aws.md), [deployment/terraform.md](./deployment/terraform.md)
and [deployment/cognito.md](./deployment/cognito.md). Where this report and those documents
disagree, those documents win.

## Status vocabulary

Five words are used, and only these five:

| Term | Meaning |
| --- | --- |
| **IMPLEMENTED** | The code exists and is wired into the composition root. It says nothing about whether it runs. |
| **TESTED** | Automated tests exist and pass. |
| **STATICALLY VALIDATED** | A tool that needs no account accepted it: `terraform validate`, `fmt -check`, `docker compose config`, lint, typecheck. |
| **RUNTIME VERIFIED** | It was really started and exercised on this machine, against a real database and real HTTP. |
| **NOT LIVE-AWS VERIFIED** | It has never run against a real AWS service or a real Cognito user pool, because none is available here. |

`PASS` in the README table always means one of the first four; the parenthetical states
which. "Should work" is never used in place of evidence.

## Built

- A modular monolith: `api`, `core`, `models`, `rag`, `repositories`, `schemas`,
  `security`, `services`, plus a single `adapters.py` composition root.
- Knowledge base, document and chunk persistence; a storage port with filesystem and S3
  adapters.
- Ingestion: PDF/Markdown/TXT parsing, structure-preserving chunking, embedding, vector
  indexing, a polling worker, an SQS queue producer and a Lambda consumer.
- The query pipeline: retrieval, a relevance threshold, a reranker seam, context assembly,
  grounded answering with citations and a per-stage trace.
- Observability: structured logs, request correlation, counters and latency summaries, and
  a metrics endpoint.
- Evaluation: a labelled dataset format, standard retrieval metrics and a report.
- An operator UI: knowledge bases, documents and passages, Q&A with traces, evaluation and
  metrics pages.
- Authentication and authorization: the `none` and `cognito` backends, an ordered
  viewer/editor/admin role scale, a fail-closed router dependency, and a PKCE browser
  sign-in flow.
- Infrastructure as code: a nine-module Terraform stack (network, storage, database,
  search, queue, iam, auth, api, ingestion) and a container stack.

## RUNTIME VERIFIED

Really executed here, against a real SQLite database and real HTTP through `TestClient`:

- upload → ingest → `ready`; query with citation and trace; `insufficient_evidence` on an
  unrelated question; evaluation metrics on the sample dataset; a metrics snapshot;
- a provider failure mapped to `502 VECTOR_STORE_ERROR`; an unusable configuration rejected
  at startup with exit 1;
- the Lambda handler consuming an API-queued document **in a separate process**, reporting
  `{"batchItemFailures": []}`, with redelivery re-ingesting idempotently;
- `502 QUEUE_UNAVAILABLE` with an unreachable queue.

Backend suite: 547 passed. Frontend suite, typecheck and production build: pass. Lint and
formatting: clean.

## STATICALLY VALIDATED

- `terraform init -backend=false`, `terraform validate` and `terraform fmt -check
  -recursive` across the root module and all nine modules.
- `docker compose config` and `docker compose --profile opensearch config`.

These prove the configuration is well-formed. They do not prove AWS will accept it.

## TESTED, against locally generated keys or stub clients

- **Cognito token verification**, against locally generated RSA keys and a signed JWKS
  document: valid access and ID tokens, expiry and leeway, wrong issuer, wrong application,
  refresh token, `alg=none`, HS256 confusion, tampered payload, unknown `kid` with
  rate-limited refresh, cache expiry, and unreachable / non-JSON / non-object / unparseable
  key documents.
- **Authorization** over HTTP: the 401 envelope and challenge header, the full
  viewer/editor/admin matrix, role checks before body validation, public probes, and an
  OpenAPI sweep asserting every `/api` path answers 401 without a token.
- **AWS adapter request/response mapping** against injected stub clients: S3 keys and
  error mapping; Bedrock `inputText`/`dimensions`/`normalize` and malformed-response
  handling; OpenSearch mapping creation, bulk body shape, k-NN filter and cosine score
  conversion; SQS message normalisation and batch-failure reporting.

## NOT LIVE-AWS VERIFIED

Nothing that needs an account or a daemon has ever run:

- no request to a real S3 bucket, Bedrock model, OpenSearch domain, SQS queue or Cognito
  user pool; a real `send_message` has never been made and the event source mapping has
  never been created;
- no Cognito user pool, app client, hosted-UI redirect or authorization-code exchange; no
  real token has ever been issued;
- `terraform plan` and `apply` have never run, no AWS resource exists, and there is no
  remote state backend;
- no image has been built or pushed to ECR, and no container has ever been started — so
  `docker compose build`/`up` and `nginx -t` are unverified too.

Adapter tests pin the mapping and the failure handling. Only a deployment can prove the
mapping matches the service.

## Known limitations

Deliberate exclusions, not oversights: no database migrations (the schema is created at
startup), no pgvector adapter, no per-knowledge-base authorization, no semantic embedding
model by default (the shipped embedder is lexical), no OCR, no faithfulness or
hallucination metric, no conversation history or query rewriting, no answer caching or
streaming, no near-duplicate deduplication, no document byte download, no archival, no
container hardening, no metric export or history, and no production high availability.

Measured negatives are reported as such rather than hidden: the reranker's improvement is
**INCONCLUSIVE** (identical metrics on the committed sample, so it ships disabled), and
semantic retrieval quality is **NOT CLAIMED** because the default embedder measures shared
vocabulary rather than meaning.
