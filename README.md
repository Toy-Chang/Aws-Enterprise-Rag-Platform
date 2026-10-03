# AWS Enterprise RAG Platform

Cloud-native enterprise knowledge retrieval and Retrieval-Augmented Generation (RAG)
platform designed around AWS services.

> **Status — Phase 2: knowledge bases, document upload and persistence.**
> Knowledge base management, document upload with a storage abstraction, relational
> metadata, configuration, structured logging, request correlation and the error
> contract are implemented and tested. Ingestion, retrieval, answer generation,
> evaluation, the frontend and every AWS adapter are **not implemented yet**. See
> [Roadmap](#roadmap) and [What is not implemented yet](#what-is-not-implemented-yet).

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

## What works today (Phase 2)

Everything in this list is implemented and covered by the 62-test suite.

### Platform foundation

- **FastAPI application factory** (`app.main.create_app`) with an explicit lifespan that
  creates the schema, logs lifecycle events, and disposes the engine on shutdown.
- **Environment-driven configuration** from `APP_*` variables and an optional `.env`
  file, validated by `pydantic-settings` — enumerated environments, log levels and log
  formats, a checked port range, and a checked upload size limit.
- **Structured logging** built on `structlog`, rendered as JSON (ready for CloudWatch
  Logs) or as a human-readable console line. Third-party records — including
  `uvicorn`'s — are routed through the same renderer, and the active request id is
  injected into every record.
- **Request correlation middleware**: reuses an inbound `X-Request-ID` when present and
  generates one otherwise, binds it to the request context, publishes it on
  `request.state`, echoes it in the response header, and emits exactly one access log
  record per request carrying method, path, status code and duration.
- **Uniform error contract** covering deliberate domain errors, framework HTTP errors
  (unmatched routes and wrong methods, with response headers such as `Allow`
  preserved), request-validation failures, and unexpected exceptions. Unexpected
  exceptions return a generic message; internal detail is logged but never returned.
- **Probes**: `GET /health` (liveness) and `GET /health/ready`, which executes a real
  `SELECT 1` against the database and reports `degraded` when it fails.
- **OpenAPI documentation** at `/docs`, `/redoc` and `/openapi.json`.

### Knowledge base management

- Create, list, get and delete knowledge bases over `/api/v1/knowledge-bases`.
- Names are unique across the platform; a duplicate returns `409 CONFLICT` with the
  offending field, and a blank name is rejected at validation time.
- Deleting a knowledge base removes its documents and their stored content.

### Document management

- Upload PDF, Markdown (`md`, `markdown`) and plain-text documents into a knowledge
  base, with the format and size enforced (`415` / `413`).
- Uploads are read in chunks against a configurable ceiling, so an oversized document
  is refused without being buffered in memory in full, and the client-supplied filename
  is reduced to its basename before use.
- Document metadata — name, content type, size, status, version, timestamps — can be
  listed and read back per knowledge base.
- Documents can be deleted, which removes both the metadata and the stored content.

### Persistence and storage

- Relational metadata through **SQLAlchemy 2.0**: `knowledge_bases` and `documents`,
  with `created_at == updated_at` on insert and `updated_at` maintained on update.
- **SQLite** locally with no daemon and no credentials; the URL is configuration, so the
  same repositories serve PostgreSQL in the AWS deployment.
- Document content behind a **`DocumentStorage` port**. The filesystem adapter ships
  now; the Amazon S3 adapter implements the same interface. Storage keys are derived
  from server-generated identifiers and validated against the storage root, so a caller
  cannot influence the path that is written.
- Transactions commit at the edge of the request: a handler that fails part-way leaves
  no partial writes.

## Architecture (Phase 2)

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
repositories ──┬── SQLAlchemy ────────── knowledge base + document metadata
               │                        (SQLite locally → PostgreSQL in AWS)
               └── DocumentStorage port ─▶ LocalFileSystemStorage (→ Amazon S3)
  ▼
exception handlers ─────── AppError → HTTPException → RequestValidationError → Exception
  ▼
response + X-Request-ID ── one error envelope, always carrying the request id
```

Layering rules the code follows:

- `app/api` owns transport; `app/core` owns configuration, request context, logging,
  the database engine and the domain error types; `app/models` owns the ORM models;
  `app/schemas` owns the wire contract; `app/repositories` owns persistence ports and
  adapters; `app/services` owns the use cases.
- Services raise `app.core.errors` types and never import FastAPI.
- Every external capability is reached through a port, so no domain code branches on
  which backend is configured.

Recorded in
[docs/architecture/decisions/0002-persistence-and-storage.md](docs/architecture/decisions/0002-persistence-and-storage.md)
and [0001-backend-foundation.md](docs/architecture/decisions/0001-backend-foundation.md).

## Technology stack

| Area | Choice | State |
|---|---|---|
| Language | Python 3.12 | **in use** |
| Web framework | FastAPI | **in use** |
| Validation & settings | Pydantic v2, pydantic-settings | **in use** |
| Persistence | SQLAlchemy 2.0 (SQLite locally) | **in use** |
| Upload parsing | python-multipart | **in use** |
| Structured logging | structlog | **in use** |
| Testing | pytest, Starlette TestClient (httpx2) | **in use** |
| Linting & formatting | ruff | **in use** |
| Frontend | React + TypeScript | planned — Phase 6 |
| Document storage | Amazon S3 (behind the existing storage port) | planned |
| Embeddings & inference | Amazon Bedrock | planned |
| Vector search | OpenSearch Serverless or PostgreSQL + pgvector; in-memory adapter behind a port locally | planned — Phase 3 |
| Authentication | Amazon Cognito | planned |
| Asynchronous ingestion | AWS Lambda | planned |
| Observability | Amazon CloudWatch | planned |
| Secrets | AWS Secrets Manager | planned |
| Infrastructure as code | Terraform | planned — Phase 7 |

## Repository structure

```
aws-enterprise-rag-platform/
├── backend/
│   ├── app/
│   │   ├── __main__.py                # `python -m app` entry point
│   │   ├── main.py                    # application factory, lifespan, resource wiring
│   │   ├── api/
│   │   │   ├── deps.py                # settings, session, engine, storage dependencies
│   │   │   ├── errors.py              # HTTP rendering of failures
│   │   │   ├── middleware.py          # request id + access logging
│   │   │   ├── router.py              # versioned API assembly
│   │   │   └── routes/
│   │   │       ├── documents.py       # upload, list, metadata, delete
│   │   │       ├── health.py          # /health, /health/ready
│   │   │       ├── knowledge_bases.py # create, list, get, delete
│   │   │       └── meta.py            # /
│   │   ├── core/
│   │   │   ├── config.py              # environment-driven Settings
│   │   │   ├── context.py             # request-scoped context variables
│   │   │   ├── db.py                  # engine, session factory, schema bootstrap
│   │   │   ├── errors.py              # AppError hierarchy
│   │   │   └── logging.py             # structlog configuration
│   │   ├── models/                    # ORM models + shared base and mixins
│   │   ├── repositories/              # persistence ports, SQLAlchemy repositories,
│   │   │                              # filesystem storage adapter
│   │   ├── schemas/                   # request and response models
│   │   └── services/                  # knowledge base and document use cases
│   ├── tests/
│   │   ├── conftest.py                # per-test SQLite database and document directory
│   │   ├── test_config.py
│   │   ├── test_logging.py
│   │   ├── api/                       # HTTP tests through TestClient
│   │   └── repositories/              # storage adapter tests
│   └── pyproject.toml
├── docs/architecture/decisions/        # ADR 0001, ADR 0002
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
repository.

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
| `APP_LOG_LEVEL` | `INFO` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG` |
| `APP_LOG_FORMAT` | `json` | `json` or `console` |

Unknown `APP_*` variables are ignored rather than rejected, so one environment can carry
configuration for several services. Invalid *known* values fail fast at startup.

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
| `GET` | `/api/v1/knowledge-bases/{id}/documents/{document_id}` | Get document metadata |
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
  "created_at": "2026-01-01T09:31:12.000000",
  "updated_at": "2026-01-01T09:31:12.000000"
}
```

`status` is `pending` for every document at this stage: nothing parses or indexes
uploads yet, and the API does not pretend otherwise.

### List a knowledge base's documents

```bash
curl -s http://127.0.0.1:8000/api/v1/knowledge-bases/$KB_ID/documents
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

## Data model

| Table | Columns |
|---|---|
| `knowledge_bases` | `id` (32-char hex UUID), `name` (unique in the platform), `description`, `created_at`, `updated_at` |
| `documents` | `id`, `knowledge_base_id` (FK, `ON DELETE CASCADE`, indexed), `name`, `content_type`, `size_bytes`, `status`, `storage_key`, `version`, `created_at`, `updated_at` |

Timestamps are stored as naive UTC, which is what SQLite preserves; moving to
PostgreSQL moves these columns to `timestamptz`. Foreign keys are enforced (the SQLite
adapter enables `PRAGMA foreign_keys` per connection).

## Observability

One access record is emitted per request, and every record produced while handling a
request carries the same `request_id`:

```json
{"event": "request_completed", "http_method": "POST",
 "http_path": "/api/v1/knowledge-bases", "http_status": 201, "duration_ms": 3.914,
 "request_id": "demo-123", "level": "info", "logger": "app.api.middleware",
 "timestamp": "2026-01-01T09:30:00.000000Z"}
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

62 deterministic tests, with no network, AWS credentials or container runtime:

- configuration defaults, environment overrides, and rejection of invalid ports, log
  formats and upload limits;
- JSON and console log rendering, request id injection, exception rendering, and level
  filtering;
- the error envelope for unmatched routes, wrong methods, deliberate domain errors,
  validation failures, and an unexpected exception whose message must not leak;
- request id reuse, generation, and replacement of a blank inbound value;
- knowledge base creation, duplicate-name conflict, blank-name rejection, listing,
  retrieval, deletion and 404s;
- document upload for every supported format, rejection of unsupported formats and
  oversized uploads, filename sanitisation, metadata retrieval, content removal on
  delete, and cascade deletion through a knowledge base;
- storage adapter round-trips, idempotent deletion, and rejection of keys that try to
  escape the storage root.

HTTP tests drive the real application through `TestClient` against a real SQLite
database, so middleware, dependency injection, transactions and exception handlers are
all exercised.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository skeleton, backend foundation: config, structured logging, request correlation, error contract, probes, tests | **complete** |
| 2 | Knowledge base management, document upload, relational metadata, storage port and filesystem adapter | **complete** |
| 3 | Ingestion pipeline: PDF/Markdown/TXT parsing, metadata-preserving chunking, embeddings, in-memory vector index behind a port | next |
| 4 | RAG query pipeline: retrieval, reranking abstraction, context construction, Bedrock-backed generation, citations, trace | planned |
| 5 | Observability (latency, retrieval and token metrics) and the evaluation module | planned |
| 6 | React + TypeScript UI: chat, knowledge bases, evaluation dashboard, system metrics | planned |
| 7 | AWS adapters (S3, Bedrock, OpenSearch/pgvector, Cognito), Terraform, docker-compose | planned |
| 8 | README and architecture documentation consolidation, roadmap and limitations | planned |

## What is not implemented yet

Stated plainly so the repository is not mistaken for more than it is:

- **No document ingestion.** Uploads are stored and registered, but nothing parses,
  chunks, embeds or indexes them. Every document stays in status `pending`.
- **No embeddings and no vector search.** There is no retrieval of any kind.
- **No language-model calls.** No Amazon Bedrock integration, no answer generation, and
  no citations returned to a caller.
- **No query, evaluation or metrics endpoints.** `POST /api/v1/query`,
  `/api/v1/evaluations` and `/api/v1/metrics` do not exist.
- **No document download.** Metadata can be read; the stored content cannot be fetched
  back over the API, because nothing needs to read it yet.
- **No archive.** Documents are deleted, not archived; there is no retention or
  soft-delete behaviour.
- **No authentication or authorization.** No Cognito integration; every endpoint is
  open, and knowledge base names occupy a single global namespace.
- **No database migrations.** The schema is created directly from the models at startup.
- **No AWS integration of any kind.** Every AWS service in the stack table is planned,
  not wired.
- **No frontend.**
- **No infrastructure as code.**

## Security notes

- No credentials are committed. `.env`, the SQLite database and the local document
  directory are git-ignored; `.env.example` contains only defaults and is safe to commit.
- All configuration arrives through environment variables, matching how ECS, Lambda and
  App Runner inject configuration and secrets.
- Uploaded filenames are reduced to their basename, and storage keys are validated
  against the storage root, so a caller cannot direct a write outside it.
- Documents are accepted by filename extension in this phase. Content sniffing belongs
  with the parsers that will actually read the bytes.
- Internal exception detail is logged server-side and never returned in a response body.
  The readiness probe reports the database exception *type* but not its message, which
  can carry a connection string.
- Request ids are caller-supplied and are therefore treated as opaque correlation data,
  not as authentication or authorization input.
- Authentication and per-knowledge-base authorization are Phase 7 work and are not
  claimed here.

## Troubleshooting

**`ImportError: dlopen(...): code signature ... have different Team IDs`**

Some Python distributions ship with the macOS hardened runtime enabled and library
validation switched on. Such an interpreter refuses to load ad-hoc-signed compiled
extensions downloaded from PyPI (`pydantic-core`, for example). Use a standard CPython
3.12 build — `brew install python@3.12` — and recreate the virtual environment:

```bash
rm -rf backend/.venv && ./scripts/bootstrap-backend.sh
```

**Starting over locally**

Delete the git-ignored state and restart the service:

```bash
rm -f backend/rag.db && rm -rf backend/data
```
