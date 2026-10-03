# AWS Enterprise RAG Platform

Cloud-native enterprise knowledge retrieval and Retrieval-Augmented Generation (RAG)
platform designed around AWS services.

> **Status — Phase 3: ingestion pipeline.**
> Knowledge base management, document upload, and the ingestion pipeline — parsing,
> structure-preserving chunking, embeddings and vector indexing — are implemented and
> tested. Retrieval, answer generation, evaluation, the frontend and every AWS adapter
> are **not implemented yet**. See [Roadmap](#roadmap) and
> [What is not implemented yet](#what-is-not-implemented-yet).

---

## The enterprise problem

Knowledge inside a large organisation is scattered across PDFs, Markdown, policy
documents, technical documentation, architecture documents, product manuals, compliance
material and operational procedures. Employees cannot locate answers quickly, and
general-purpose "chat with your documents" tools produce fluent answers that cannot be
traced back to a source. For compliance, security and operations work, an untraceable
answer is worse than no answer.

This platform is the target design for that problem:

- documents are uploaded into curated **knowledge bases**;
- an **ingestion pipeline** parses, chunks and embeds them;
- questions are answered by a **retrieval-augmented generation pipeline** that returns
  the evidence it used, with citations and retrieval scores;
- when the knowledge base does not contain supporting evidence, the platform says so
  instead of inventing an answer;
- every request is observable — latency, retrieval behaviour, token usage, failures.

## What works today (Phase 3)

Everything in this list is implemented and covered by the 127-test suite.

### Platform foundation

- **FastAPI application factory** (`app.main.create_app`) with an explicit lifespan that
  creates the schema, requeues interrupted ingestions, rebuilds the vector index, starts
  the ingestion worker, and disposes the engine on shutdown.
- **Environment-driven configuration** from `APP_*` variables and an optional `.env`
  file, validated by `pydantic-settings`: enumerated environments, log levels and log
  formats, a checked port range, a checked upload limit, and chunk settings that cannot
  contradict each other.
- **Structured logging** built on `structlog`, rendered as JSON (ready for CloudWatch
  Logs) or as a human-readable console line. Third-party records — including
  `uvicorn`'s — go through the same renderer, and the active request id is injected into
  every record.
- **Request correlation middleware**: reuses an inbound `X-Request-ID` when present and
  generates one otherwise, binds it to the request context, publishes it on
  `request.state`, echoes it in the response header, and emits exactly one access log
  record per request carrying method, path, status code and duration.
- **Uniform error contract** covering deliberate domain errors, framework HTTP errors
  (with response headers such as `Allow` preserved), request-validation failures, and
  unexpected exceptions. Internal detail is logged, never returned.
- **Probes**: `GET /health` and `GET /health/ready`, which executes a real `SELECT 1` and
  reports `degraded` when it fails.
- **OpenAPI documentation** at `/docs`, `/redoc` and `/openapi.json`.

### Knowledge base and document management

- Create, list, get and delete knowledge bases; names are unique across the platform, a
  duplicate returns `409 CONFLICT`, and deleting a knowledge base removes its documents,
  their chunks, their vectors and their stored content.
- Upload PDF, Markdown (`md`, `markdown`) and plain-text documents, with format and size
  enforced (`415` / `413`). Uploads are read in chunks against the ceiling, so an
  oversized document is refused without being buffered in memory in full, and the
  client-supplied filename is reduced to its basename.
- List documents, read one document's metadata and status, list its indexed passages, and
  delete it. `POST .../reprocess` re-runs ingestion, which is the recovery path for a
  document that failed to parse.

### Ingestion pipeline

- **Parsing** by extension. PDFs are read page by page with `pypdf`; Markdown is split on
  its headings, which become metadata; plain text is taken as written. Non-UTF-8 input is
  decoded with replacement *and reported*, and a document with no extractable text fails
  with that reason instead of indexing nothing.
- **Chunking** that preserves structure: every passage records its page number, its
  heading path, its index and the character offsets it came from, with offsets trimmed to
  bound the stored content exactly. Windows prefer a paragraph break, then a line break,
  then a sentence, then a space, and overlap so a sentence on a boundary stays retrievable
  from both sides.
- **Embeddings** behind an `EmbeddingModel` port, with a dependency-free local adapter
  (see [Retrieval quality](#retrieval-quality)).
- **A vector index** behind a `VectorStore` port with an in-memory cosine adapter. It
  stores identifiers and vectors; passage text stays in the database, so a search result
  resolves to its passage instead of the index keeping a second copy of the corpus.
- **An ingestion worker** that polls for queued documents, so no request ever waits for
  parsing, chunking or embedding. Documents move `pending → processing → ready`, or to
  `failed` with a reason a caller can read.
- **Self-healing state**: the invariant is that a document is `ready` if and only if its
  chunks are stored and indexed. A failure clears both, `reprocess` clears both before
  queueing again, and a restart requeues documents caught mid-ingestion and rebuilds the
  index from the stored embeddings.

### Persistence and storage

- Relational metadata through **SQLAlchemy 2.0**: `knowledge_bases`, `documents` and
  `chunks`, with `created_at == updated_at` on insert and `updated_at` maintained on
  update.
- **SQLite** locally in WAL mode, so the worker can read while a request writes; the URL
  is configuration, so the same repositories serve PostgreSQL in the AWS deployment.
- Document content behind a **`DocumentStorage` port**. The filesystem adapter ships now;
  the Amazon S3 adapter implements the same interface. Storage keys are derived from
  server-generated identifiers and validated against the storage root.
- Transactions commit at the edge of the request: a handler that fails part-way leaves no
  partial writes.

## Architecture (Phase 3)

Requests and ingestion are separate paths, and they share only the database and the
adapters:

```
client
  │  X-Request-ID (optional)
  ▼
RequestContextMiddleware ── assign or reuse request id, time the request, emit one record
  ▼
router ─────────────────── /            /health   /health/ready
  │                        /api/v1/knowledge-bases…
  ▼
services ───────────────── domain rules: uniqueness, format, existence, status
  ▼
repositories ──┬── SQLAlchemy ────────── knowledge bases, documents, chunks
               │                        (SQLite locally → PostgreSQL in AWS)
               └── DocumentStorage port ─▶ LocalFileSystemStorage (→ Amazon S3)

ingestion worker (own thread, own sessions)
  │  polls documents in `pending`
  ▼
pending ─▶ processing ─▶ parse ─▶ chunk ─▶ embed ─▶ store chunks ─▶ index ─▶ ready
                │                                                      │
                └──────────────────── any failure ─────────────────────┴─▶ failed
                                                                        (reason recorded)

EmbeddingModel port ──▶ HashingEmbeddingModel        (→ Amazon Bedrock)
VectorStore port ─────▶ InMemoryVectorStore          (→ OpenSearch / pgvector)
```

Layering rules the code follows:

- `app/api` owns transport; `app/core` owns configuration, request context, logging, the
  database engine and the domain error types; `app/models` owns the ORM models;
  `app/schemas` owns the wire contract; `app/repositories` owns persistence ports and
  adapters; `app/ingestion` owns parsing and chunking; `app/rag` owns the embedding and
  vector-index ports; `app/services` owns the use cases, including the worker.
- Services raise `app.core.errors` types and never import FastAPI.
- Every external capability is reached through a port, so no domain code branches on which
  backend is configured.

Recorded in
[ADR 0003](docs/architecture/decisions/0003-ingestion-and-retrieval-adapters.md),
[ADR 0002](docs/architecture/decisions/0002-persistence-and-storage.md) and
[ADR 0001](docs/architecture/decisions/0001-backend-foundation.md).

## Technology stack

| Area | Choice | State |
|---|---|---|
| Language | Python 3.12 | **in use** |
| Web framework | FastAPI | **in use** |
| Validation & settings | Pydantic v2, pydantic-settings | **in use** |
| Persistence | SQLAlchemy 2.0 (SQLite in WAL mode locally) | **in use** |
| Upload parsing | python-multipart | **in use** |
| PDF text extraction | pypdf | **in use** |
| Structured logging | structlog | **in use** |
| Testing | pytest, Starlette TestClient (httpx2) | **in use** |
| Linting & formatting | ruff | **in use** |
| Embeddings | Bedrock (the local adapter is a lexical hashing baseline) | port **in use**, AWS adapter planned |
| Vector search | OpenSearch Serverless or PostgreSQL + pgvector (in-memory adapter locally) | port **in use**, AWS adapter planned |
| Asynchronous ingestion | AWS Lambda + queue (local polling worker) | worker **in use**, AWS adapter planned |
| Frontend | React + TypeScript | planned — Phase 6 |
| Document storage | Amazon S3 (behind the existing storage port) | planned |
| Answer generation | Amazon Bedrock | planned — Phase 4 |
| Authentication | Amazon Cognito | planned |
| Observability | Amazon CloudWatch | planned — Phase 5 |
| Secrets | AWS Secrets Manager | planned |
| Infrastructure as code | Terraform | planned — Phase 7 |

## Repository structure

```
aws-enterprise-rag-platform/
├── backend/
│   ├── app/
│   │   ├── __main__.py                # `python -m app` entry point
│   │   ├── main.py                    # factory, lifespan, resource wiring
│   │   ├── api/
│   │   │   ├── deps.py                # settings, session, engine, storage, index
│   │   │   ├── errors.py              # HTTP rendering of failures
│   │   │   ├── middleware.py          # request id + access logging
│   │   │   ├── router.py              # versioned API assembly
│   │   │   └── routes/
│   │   │       ├── documents.py       # upload, list, metadata, chunks, reprocess
│   │   │       ├── health.py          # /health, /health/ready
│   │   │       ├── knowledge_bases.py # create, list, get, delete
│   │   │       └── meta.py            # /
│   │   ├── core/
│   │   │   ├── config.py              # environment-driven Settings
│   │   │   ├── context.py             # request-scoped context variables
│   │   │   ├── db.py                  # engine, session factory, SQLite pragmas
│   │   │   ├── errors.py              # AppError hierarchy
│   │   │   └── logging.py             # structlog configuration
│   │   ├── ingestion/
│   │   │   ├── chunking.py            # structure-preserving windows + offsets
│   │   │   └── parsers.py             # PDF, Markdown and text extraction
│   │   ├── models/                    # ORM models + shared base and mixins
│   │   ├── rag/
│   │   │   ├── embeddings.py          # EmbeddingModel port
│   │   │   ├── hashing_embeddings.py  # local lexical adapter
│   │   │   ├── vector_store.py        # VectorStore port and records
│   │   │   └── in_memory_vector_store.py
│   │   ├── repositories/              # SQLAlchemy repositories, storage port + adapter
│   │   ├── schemas/                   # request and response models
│   │   └── services/                  # use cases: documents, knowledge bases,
│   │                                  # ingestion, worker
│   ├── tests/
│   │   ├── conftest.py                # per-test database, storage dir, ingestion helper
│   │   ├── test_config.py
│   │   ├── test_logging.py
│   │   ├── api/                       # HTTP tests through TestClient
│   │   ├── ingestion/                 # parser and chunker tests + a PDF builder
│   │   └── rag/                       # embedding and vector index tests
│   └── pyproject.toml
├── docs/architecture/decisions/        # ADR 0001, 0002, 0003
├── scripts/bootstrap-backend.sh
├── .env.example
├── .gitignore
└── README.md
```

`frontend/` and `infrastructure/terraform/` are introduced in the phases that populate
them; they are intentionally absent rather than committed empty.

## Local development

### Prerequisites

- CPython **3.12** on `PATH` as `python3.12` (for example `brew install python@3.12`).
- No AWS account, no database server and no container runtime are required.

### Setup

```bash
./scripts/bootstrap-backend.sh
```

Or manually:

```bash
python3.12 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -e "backend[dev]"
```

### Run

```bash
cd backend
python -m app
```

The server listens on <http://127.0.0.1:8000>, with interactive documentation at
<http://127.0.0.1:8000/docs>. On first start it creates the SQLite database
(`backend/rag.db`) and the document directory (`backend/data/`); both are git-ignored.

`python -m app` deliberately disables uvicorn's own access log and logging
configuration: the request middleware already emits a structured access record, so
leaving uvicorn's configuration in place would duplicate every line.

### Test and lint

```bash
cd backend
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Each test gets its own SQLite database and document directory under pytest's temporary
directory, so the suite is deterministic, needs no network, and never writes into the
repository. The ingestion worker thread is disabled in tests and the pipeline is driven
directly, so no test depends on timing; one test runs the real thread and waits for the
result.

## Configuration

All settings are optional and read from `APP_*` environment variables, then from an
optional `.env` file in the working directory. Start from the template:

```bash
cp .env.example backend/.env
```

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `aws-enterprise-rag-platform` | Service identifier used in logs and probes |
| `APP_DISPLAY_NAME` | `AWS Enterprise RAG Platform` | OpenAPI title |
| `APP_VERSION` | `0.1.0` | Reported version |
| `APP_ENVIRONMENT` | `local` | `local`, `test`, `development`, `staging`, `production` |
| `APP_API_VERSION` | `v1` | API version advertised by `GET /` |
| `APP_API_V1_PREFIX` | `/api/v1` | Mount point of the versioned API |
| `APP_HOST` | `127.0.0.1` | Bind address for `python -m app` |
| `APP_PORT` | `8000` | Bind port (validated to 1–65535) |
| `APP_RELOAD` | `false` | Enable uvicorn auto-reload |
| `APP_REQUEST_ID_HEADER` | `X-Request-ID` | Header used to read and echo the request id |
| `APP_DATABASE_URL` | `sqlite:///./rag.db` | SQLAlchemy database URL |
| `APP_STORAGE_DIR` | `./data` | Root directory for the local storage adapter |
| `APP_MAX_UPLOAD_SIZE_BYTES` | `10485760` | Largest accepted document, in bytes |
| `APP_CHUNK_SIZE_CHARS` | `1200` | Chunk window size in **characters**, not tokens |
| `APP_CHUNK_OVERLAP_CHARS` | `200` | Overlap between windows; must be smaller than the size |
| `APP_EMBEDDING_DIMENSIONS` | `256` | Vector width; changing it invalidates stored embeddings |
| `APP_INGESTION_WORKER_ENABLED` | `true` | Run the ingestion worker thread |
| `APP_INGESTION_POLL_SECONDS` | `0.5` | Wait between empty worker cycles |
| `APP_INGESTION_BATCH_SIZE` | `10` | Documents the worker takes per cycle |
| `APP_LOG_LEVEL` | `INFO` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG` |
| `APP_LOG_FORMAT` | `json` | `json` or `console` |

Unknown `APP_*` variables are ignored rather than rejected, so one environment can carry
configuration for several services. Invalid *known* values fail fast at startup — including
a chunk overlap that is not smaller than the chunk size.

## How ingestion works

1. `POST /api/v1/knowledge-bases/{id}/documents` writes the content to the document
   store, inserts a row in `pending`, and answers `201`. It does no parsing.
2. The ingestion worker picks up `pending` documents, oldest first.
3. It marks the document `processing` and commits that before parsing, so progress is
   visible and a crash leaves an honest state rather than a document that never started.
4. It reads the content back from the store and parses it according to the extension.
5. It chunks the parsed blocks, keeping page numbers, heading paths and character offsets.
6. It embeds every chunk, stores the chunks and their vectors in one transaction, and
   marks the document `ready`.
7. It updates the vector index. The index is updated only after the chunks are committed,
   because a vector pointing at a row nobody can read would break citation resolution.

Any failure along the way clears the document's chunks, removes its vectors and records
`failed` with a reason. At startup, documents left in `processing` are queued again and
the index is rebuilt from the stored embeddings.

Ingestion is deliberately *not* a FastAPI background task. FastAPI runs a response's
background tasks before it exits the request's dependency generators, so such a task runs
while the upload's transaction is still open: it cannot see the row it was meant to
process, and its writes contend with the request's write lock. The reasoning and the
transaction trace are in
[ADR 0003](docs/architecture/decisions/0003-ingestion-and-retrieval-adapters.md).

## API

Infrastructure endpoints live at the root; everything else is versioned.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Service identity and advertised API version |
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe, including a database check |
| `POST` | `/api/v1/knowledge-bases` | Create a knowledge base |
| `GET` | `/api/v1/knowledge-bases` | List knowledge bases |
| `GET` | `/api/v1/knowledge-bases/{id}` | Get one knowledge base |
| `DELETE` | `/api/v1/knowledge-bases/{id}` | Delete a knowledge base and its documents |
| `POST` | `/api/v1/knowledge-bases/{id}/documents` | Upload a document |
| `GET` | `/api/v1/knowledge-bases/{id}/documents` | List a knowledge base's documents |
| `GET` | `/api/v1/knowledge-bases/{id}/documents/{document_id}` | Get document metadata and status |
| `GET` | `/api/v1/knowledge-bases/{id}/documents/{document_id}/chunks` | List the indexed passages |
| `POST` | `/api/v1/knowledge-bases/{id}/documents/{document_id}/reprocess` | Re-run ingestion |
| `DELETE` | `/api/v1/knowledge-bases/{id}/documents/{document_id}` | Delete a document |

### Create a knowledge base

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge-bases \
  -H 'Content-Type: application/json' \
  -d '{"name": "Platform Runbooks", "description": "Operational procedures."}'
```
```json
{
  "id": "0f4c1b2a8d5e4f6b9c3a1d2e7f8b0c11",
  "name": "Platform Runbooks",
  "description": "Operational procedures.",
  "created_at": "2026-01-01T09:30:00.000000",
  "updated_at": "2026-01-01T09:30:00.000000"
}
```

### Upload a document

```bash
curl -s -X POST \
  http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/documents \
  -F 'file=@docs/incident-response.md;type=text/markdown'
```
```json
{
  "id": "3a7d9c1e5b2f4a8c9d0e1f2a3b4c5d6e",
  "knowledge_base_id": "0f4c1b2a8d5e4f6b9c3a1d2e7f8b0c11",
  "name": "incident-response.md",
  "content_type": "text/markdown",
  "size_bytes": 2048,
  "status": "pending",
  "version": 1,
  "chunk_count": 0,
  "error_message": null,
  "created_at": "2026-01-01T09:31:12.000000",
  "updated_at": "2026-01-01T09:31:12.000000"
}
```

`status` is `pending` because ingestion runs after the response. Poll the metadata
endpoint until it settles:

```bash
curl -s http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/documents/$DOC_ID
```
```json
{
  "id": "3a7d9c1e5b2f4a8c9d0e1f2a3b4c5d6e",
  "status": "ready",
  "chunk_count": 4,
  "error_message": null
}
```

### Inspect the indexed passages

```bash
curl -s http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/documents/$DOC_ID/chunks
```
```json
[
  {
    "id": "b1c2d3e4f5a60718293a4b5c6d7e8f90",
    "document_id": "3a7d9c1e5b2f4a8c9d0e1f2a3b4c5d6e",
    "chunk_index": 0,
    "content": "Incident response\n\nPage the on-call engineer, then open a ticket.",
    "char_start": 0,
    "char_end": 62,
    "page_number": null,
    "heading_path": ["Incident response"],
    "created_at": "2026-01-01T09:31:12.140000"
  }
]
```

## Error contract

Every non-successful response uses one envelope:

```json
{
  "request_id": "0f4c1b2a8d5e4f6b9c3a1d2e7f8b0c11",
  "error": {
    "code": "NOT_FOUND",
    "message": "Not Found",
    "details": {}
  }
}
```

| Status | `code` | Raised by |
|---|---|---|
| 400 | `BAD_REQUEST` | `BadRequestError` |
| 404 | `NOT_FOUND` | unmatched route, `NotFoundError` (unknown knowledge base or document) |
| 405 | `METHOD_NOT_ALLOWED` | wrong HTTP method (the `Allow` header is preserved) |
| 409 | `CONFLICT` | `ConflictError` — a knowledge base name that is already taken |
| 413 | `PAYLOAD_TOO_LARGE` | upload above `APP_MAX_UPLOAD_SIZE_BYTES` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | `UnsupportedMediaTypeError` — a format outside PDF/Markdown/TXT |
| 422 | `UNPROCESSABLE_ENTITY` | request validation, with per-field detail in `details.errors` |
| 500 | `INTERNAL_ERROR` | unexpected exception — logged in full, reported generically |

An ingestion failure is **not** an HTTP error: the upload has already succeeded. It is
reported on the document as `status: "failed"` with `error_message` explaining why.

## Data model

| Table | Columns |
|---|---|
| `knowledge_bases` | `id` (32-char hex UUID), `name` (unique in the platform), `description`, `created_at`, `updated_at` |
| `documents` | `id`, `knowledge_base_id` (FK, `ON DELETE CASCADE`, indexed), `name`, `content_type`, `size_bytes`, `status`, `storage_key`, `version`, `chunk_count`, `error_message`, `created_at`, `updated_at` |
| `chunks` | `id`, `document_id` (FK, cascade, indexed), `knowledge_base_id` (FK, cascade, indexed), `chunk_index`, `content`, `char_start`, `char_end`, `page_number`, `heading_path` (JSON), `embedding` (JSON), `created_at` |

Timestamps are stored as naive UTC, which is what SQLite preserves; moving to PostgreSQL
moves these columns to `timestamptz`. Foreign keys are enforced, and the SQLite adapter
enables `PRAGMA foreign_keys` and `journal_mode=WAL` per connection so the worker can read
while a request writes.

Storing each embedding as a JSON array beside its chunk is a deliberate local compromise:
it makes the in-memory index pure derived state that a restart can rebuild without
re-embedding the corpus. A native `vector` column (pgvector) or an external index replaces
it in the AWS deployment.

## Retrieval quality

The local embedding adapter is `HashingEmbeddingModel`: hashed term frequencies,
sublinear weighting, L2-normalised. **It is a lexical model, not a semantic one.** It
retrieves passages that share vocabulary with the query and knows nothing about meaning,
paraphrase or synonyms.

It exists so that ingestion and retrieval run end to end, offline and deterministically,
and so that the vector index can be tested with exact assertions. It is not a claim of
retrieval quality, and no quality metric is reported anywhere in this repository. The
Amazon Bedrock embedding model implements the same port and replaces it in the AWS
deployment; retrieval quality is measured in Phase 5, after there is a retrieval pipeline
to measure.

## Observability

One access record is emitted per request, and every record produced while handling a
request carries the same `request_id`:

```json
{"event": "request_completed", "http_method": "POST",
 "http_path": "/api/v1/knowledge-bases", "http_status": 201, "duration_ms": 3.914,
 "request_id": "demo-123", "level": "info", "logger": "app.api.middleware",
 "timestamp": "2026-01-01T09:30:00.000000Z"}
```

Successful ingestion is reported with what it did, and failure with the full traceback:

```json
{"event": "document_ingested", "document_id": "3a7d…", "knowledge_base_id": "0f4c…",
 "parser": "markdown", "chunk_count": 4, "notes": [], "level": "info",
 "logger": "app.services.ingestion", "timestamp": "2026-01-01T09:31:12.140000Z"}
```

Set `APP_LOG_FORMAT=json` (the default) so CloudWatch Logs can index these fields as
structured data; `APP_LOG_FORMAT=console` renders the same records for local reading.
Latency percentiles, retrieval metrics, token usage and failure counters are added in
Phase 5 — no metric is reported before it is actually measured.

## Testing

```bash
cd backend
python -m pytest -q
```

127 deterministic tests, with no network, AWS credentials or container runtime:

- configuration defaults, environment overrides, and rejection of invalid ports, log
  formats, upload limits, chunk sizes, overlaps, vector widths and poll intervals;
- JSON and console log rendering, request id injection, exception rendering, and level
  filtering;
- the error envelope for unmatched routes, wrong methods, deliberate domain errors,
  validation failures, and an unexpected exception whose message must not leak;
- knowledge base creation, duplicate-name conflict, blank-name rejection, listing,
  retrieval, deletion and 404s;
- document upload for every supported format, rejection of unsupported formats and
  oversized uploads, filename sanitisation, metadata retrieval, content removal on delete,
  and cascade deletion through a knowledge base;
- parsing of every format, including a generated multi-page PDF, heading paths, heading
  level jumps, blank PDF pages, non-UTF-8 input and a corrupt file;
- chunk window sizes, overlap, exact character offsets, paragraph-boundary preference,
  metadata propagation, sequential indexes, and termination at tiny sizes;
- embedding determinism, dimensionality, unit length, and that shared vocabulary scores
  above unrelated text;
- vector index ranking, knowledge-base scoping, `top_k`, upsert replacement, deletion,
  stable tie ordering, zero vectors and dimension mismatches;
- end to end through HTTP: an upload settles at `ready`, its chunks carry their metadata,
  the content becomes retrievable by the index, an unparsable document settles at `failed`
  with a reason and is not indexed, `reprocess` rebuilds chunks without duplicating them,
  deletion clears chunks and vectors, a restart rebuilds the index, an interrupted
  ingestion is queued again, and the worker thread actually processes an upload.

HTTP tests drive the real application through `TestClient` against a real SQLite database,
so middleware, dependency injection, transactions and exception handlers are all
exercised.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository skeleton, backend foundation: config, logging, request correlation, error contract, probes, tests | **complete** |
| 2 | Knowledge base management, document upload, relational metadata, storage port and filesystem adapter | **complete** |
| 3 | Ingestion: PDF/Markdown/TXT parsing, structure-preserving chunking, embeddings, vector index behind ports, ingestion worker | **complete** |
| 4 | RAG query pipeline: retrieval, relevance threshold, reranking abstraction, context construction, Bedrock-backed generation, citations, trace | next |
| 5 | Observability (latency, retrieval and token metrics) and the evaluation module | planned |
| 6 | React + TypeScript UI: chat, knowledge bases, evaluation dashboard, system metrics | planned |
| 7 | AWS adapters (S3, Bedrock, OpenSearch/pgvector, Cognito, Lambda + queue), Terraform, docker-compose | planned |
| 8 | README and architecture documentation consolidation, roadmap and limitations | planned |

## What is not implemented yet

Stated plainly so the repository is not mistaken for more than it is:

- **No retrieval endpoint.** There is no way to query a knowledge base over HTTP; the
  vector index is reachable only from inside the process. Retrieval is Phase 4.
- **No answer generation.** No Amazon Bedrock integration, no LLM calls, no citations
  returned to a caller, no streaming.
- **No reranking, no relevance threshold and no query rewriting.** The vector store
  returns the best candidates regardless of score by design.
- **No semantic embeddings.** The local adapter is lexical; see
  [Retrieval quality](#retrieval-quality).
- **No OCR.** Scanned PDFs fail with "no text could be extracted" rather than being
  recognised.
- **No token-accurate chunking.** Window sizes are characters; a model tokenizer arrives
  with the generation adapter.
- **No evaluation or metrics endpoints.** `POST /api/v1/evaluations` and
  `/api/v1/metrics` do not exist, and no quality metric is claimed.
- **No document download.** Metadata and chunks can be read; the stored bytes cannot be
  fetched back over the API.
- **No archive.** Documents are deleted, not archived; there is no retention or
  soft-delete behaviour.
- **No authentication or authorization.** Every endpoint is open, and knowledge base names
  occupy a single global namespace.
- **No database migrations.** The schema is created directly from the models at startup.
- **No multi-process ingestion.** The worker assumes one process; two would both poll the
  same documents. A queue is what makes claiming work safe.
- **No AWS integration of any kind.** Every AWS service in the stack table is planned, not
  wired.
- **No frontend.**
- **No infrastructure as code.**

## Security notes

- No credentials are committed. `.env`, the SQLite database and the local document
  directory are git-ignored; `.env.example` contains only defaults and is safe to commit.
- All configuration arrives through environment variables, matching how ECS, Lambda and
  App Runner inject configuration and secrets.
- Uploaded filenames are reduced to their basename, and storage keys are validated against
  the storage root, so a caller cannot direct a write outside it.
- Documents are accepted by filename extension. Content sniffing belongs with the parsers,
  which read the bytes but do not validate magic numbers.
- Internal exception detail is logged server-side and never returned in a response body.
  An ingestion failure reports either a known-safe message or the exception *type*, and
  the readiness probe reports the database exception type but not its message, which can
  carry a connection string.
- Request ids are caller-supplied and are therefore treated as opaque correlation data,
  not as authentication or authorization input.
- Authentication and per-knowledge-base authorization are Phase 7 work and are not claimed
  here.

## Troubleshooting

**`ImportError: dlopen(...): code signature ... have different Team IDs`**

Some Python distributions ship with the macOS hardened runtime enabled and library
validation switched on. Such an interpreter refuses to load ad-hoc-signed compiled
extensions downloaded from PyPI (`pydantic-core`, for example). Use a standard CPython
3.12 build — `brew install python@3.12` — and recreate the virtual environment:

```bash
rm -rf backend/.venv && ./scripts/bootstrap-backend.sh
```

**Documents stay in `pending`**

The ingestion worker is what moves them. Check that `APP_INGESTION_WORKER_ENABLED` is not
`false`, and look for `ingestion_worker_started` and `document_ingested` in the logs. A
document that failed shows why in `error_message`, and `POST .../reprocess` retries it.

**`ValueError: ... dimensions, but the index is configured for ...`**

Stored embeddings were produced with a different `APP_EMBEDDING_DIMENSIONS`. Changing the
vector width invalidates every stored vector, and the index refuses to mix widths rather
than scoring nonsense. Re-ingest the documents, or start over:

```bash
rm -f backend/rag.db && rm -rf backend/data
```

**Starting over locally**

```bash
rm -f backend/rag.db backend/rag.db-wal backend/rag.db-shm && rm -rf backend/data
```
