# AWS Enterprise RAG Platform

Cloud-native enterprise knowledge retrieval and Retrieval-Augmented Generation (RAG)
platform designed around AWS services.

> **Status — Phase 1: backend foundation.**
> The API skeleton, configuration, structured logging, request correlation and error
> contract are implemented and tested. Document ingestion, retrieval, generation,
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

## What works today (Phase 1)

Everything in this list is implemented and covered by the test suite.

- **FastAPI application factory** (`app.main.create_app`) with an explicit lifespan that
  logs service start and stop.
- **Environment-driven configuration** from `APP_*` variables and an optional `.env`
  file, validated by `pydantic-settings` (enumerated environments, log levels and log
  formats; port range checked).
- **Structured logging** built on `structlog`, rendered as JSON (ready for CloudWatch
  Logs) or as a human-readable console line. Third-party records — including
  `uvicorn`'s — are routed through the same renderer, and the active request id is
  injected into every record.
- **Request correlation middleware**: reuses an inbound `X-Request-ID` when present and
  generates a UUID4 otherwise, binds it to the request context, publishes it on
  `request.state`, echoes it in the response header, and emits exactly one access log
  record per request carrying method, path, status code and duration.
- **Uniform error contract** covering deliberate application errors (`AppError` and
  subclasses), framework HTTP errors (unmatched routes, wrong methods — response headers
  such as `Allow` are preserved), request-validation failures, and unexpected
  exceptions. Unexpected exceptions return a generic message; internal detail is logged
  but never returned to the caller.
- **Probes and metadata**: `GET /`, `GET /health`, `GET /health/ready`.
- **OpenAPI documentation** at `/docs`, `/redoc` and `/openapi.json`, generated from the
  Pydantic response models.
- **Test suite**: configuration and logging unit tests plus HTTP integration tests
  driven through `TestClient`.

## Architecture (Phase 1)

```
client
  │  X-Request-ID (optional)
  ▼
RequestContextMiddleware ── assign or reuse request id, bind it to the request context,
  │                          time the request, emit one access record
  ▼
router ──────────────────── GET /   GET /health   GET /health/ready
  ▼
exception handlers ──────── AppError → HTTPException → RequestValidationError → Exception
  ▼
response + X-Request-ID ─── one error envelope, always carrying the request id
```

Deliberate structural decisions:

- **Layers are separated.** `app/api` owns transport, `app/core` owns configuration,
  request context and logging, `app/schemas` owns the wire contract. Later phases add
  `app/rag`, `app/ingestion`, `app/evaluation` and `app/integrations` without touching
  the HTTP layer.
- **Settings are injected, not imported.** Routes resolve settings through a dependency
  that reads `app.state.settings`, so tests and alternate deployments build an app with
  their own configuration instead of depending on process state.
- **Failures leave through one envelope.** Clients parse an error once, and every
  failure carries the same request id that appears in the logs — which is what makes a
  production incident debuggable.

Recorded in [docs/architecture/decisions/0001-backend-foundation.md](docs/architecture/decisions/0001-backend-foundation.md).

## Technology stack

| Area | Choice | State |
|---|---|---|
| Language | Python 3.12 | **in use** |
| Web framework | FastAPI | **in use** |
| Validation & settings | Pydantic v2, pydantic-settings | **in use** |
| Structured logging | structlog | **in use** |
| Testing | pytest, Starlette TestClient (httpx) | **in use** |
| Linting | ruff | **in use** |
| Frontend | React + TypeScript | planned — Phase 6 |
| Document storage | Amazon S3 | planned |
| Embeddings & inference | Amazon Bedrock | planned |
| Vector search | OpenSearch Serverless or PostgreSQL + pgvector; a local in-memory adapter behind a port | planned — Phase 3 |
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
│   │   ├── __init__.py
│   │   ├── __main__.py            # `python -m app` entry point
│   │   ├── main.py                # application factory and lifespan
│   │   ├── api/
│   │   │   ├── deps.py            # shared FastAPI dependencies
│   │   │   ├── errors.py          # AppError hierarchy and exception handlers
│   │   │   ├── middleware.py      # request id + access logging
│   │   │   └── routes/
│   │   │       ├── health.py      # /health, /health/ready
│   │   │       └── meta.py        # /
│   │   ├── core/
│   │   │   ├── config.py          # environment-driven Settings
│   │   │   ├── context.py         # request-scoped context variables
│   │   │   └── logging.py         # structlog configuration
│   │   └── schemas/
│   │       └── common.py          # response and error models
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_config.py
│   │   ├── test_logging.py
│   │   └── api/
│   │       ├── test_errors.py
│   │       └── test_health.py
│   └── pyproject.toml
├── docs/
│   └── architecture/decisions/    # architecture decision records
├── scripts/
│   └── bootstrap-backend.sh
├── .env.example
├── .gitignore
└── README.md
```

`frontend/` and `infrastructure/terraform/` are introduced in the phases that populate
them; they are intentionally absent rather than committed empty.

## Local development

### Prerequisites

- CPython **3.12** on `PATH` as `python3.12` (for example `brew install python@3.12`).
- No AWS account is required for the current phase.

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
<http://127.0.0.1:8000/docs>.

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
| `APP_HOST` | `127.0.0.1` | Bind address for `python -m app` |
| `APP_PORT` | `8000` | Bind port (validated to 1–65535) |
| `APP_RELOAD` | `false` | Enable uvicorn auto-reload |
| `APP_REQUEST_ID_HEADER` | `X-Request-ID` | Header used to read and echo the request id |
| `APP_LOG_LEVEL` | `INFO` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG` |
| `APP_LOG_FORMAT` | `json` | `json` or `console` |

Unknown `APP_*` variables are ignored rather than rejected, so one environment can carry
configuration for several services. Invalid *known* values fail fast at startup.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Service identity and advertised API version |
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (dependency checks are added with their adapters) |

### Examples

```bash
curl -s http://127.0.0.1:8000/ | jq
```
```json
{
  "service": "aws-enterprise-rag-platform",
  "display_name": "AWS Enterprise RAG Platform",
  "version": "0.1.0",
  "environment": "local",
  "api_version": "v1"
}
```

```bash
curl -s http://127.0.0.1:8000/health | jq
```
```json
{
  "status": "ok",
  "service": "aws-enterprise-rag-platform",
  "version": "0.1.0",
  "environment": "local"
}
```

```bash
curl -si -H 'X-Request-ID: demo-123' http://127.0.0.1:8000/health/ready | head -n 12
```
```json
{
  "status": "ok",
  "service": "aws-enterprise-rag-platform",
  "version": "0.1.0",
  "environment": "local",
  "checks": []
}
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
| 404 | `NOT_FOUND` | unmatched route, `NotFoundError` |
| 405 | `METHOD_NOT_ALLOWED` | wrong HTTP method (the `Allow` header is preserved) |
| 409 | `CONFLICT` | `ConflictError` |
| 422 | `UNPROCESSABLE_ENTITY` | request validation, with per-field detail in `details.errors` |
| 500 | `INTERNAL_ERROR` | unexpected exception — logged in full, reported generically |

## Observability

One access record is emitted per request, and every record produced while handling a
request carries the same `request_id`:

```json
{"event": "request_completed", "http_method": "GET", "http_path": "/health",
 "http_status": 200, "duration_ms": 1.284, "request_id": "demo-123",
 "level": "info", "logger": "app.api.middleware", "timestamp": "2026-01-01T00:00:00.000000Z"}
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

The suite is deterministic and requires no network or AWS credentials. HTTP tests drive
the real application through `TestClient`, so middleware, dependency injection and
exception handlers are all exercised — including that a deliberately raised internal
error never leaks its message to the client.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository skeleton, backend foundation: config, structured logging, request correlation, error contract, probes, tests | **complete** |
| 2 | Knowledge base management and document upload, with a local filesystem storage adapter | next |
| 3 | Ingestion pipeline: PDF/Markdown/TXT parsing, metadata-preserving chunking, embeddings, in-memory vector index behind a port | planned |
| 4 | RAG query pipeline: retrieval, reranking abstraction, context construction, Bedrock-backed generation, citations, trace | planned |
| 5 | Observability (latency, retrieval and token metrics) and the evaluation module | planned |
| 6 | React + TypeScript UI: chat, knowledge bases, evaluation dashboard, system metrics | planned |
| 7 | AWS adapters (S3, Bedrock, OpenSearch/pgvector, Cognito), Terraform, docker-compose | planned |
| 8 | README and architecture documentation consolidation, roadmap and limitations | planned |

## What is not implemented yet

Stated plainly so the repository is not mistaken for more than it is:

- **No document ingestion.** No PDF, Markdown or TXT parsing, no chunking, no metadata
  persistence.
- **No embeddings and no vector search.** No retrieval of any kind.
- **No language-model calls.** No Amazon Bedrock integration, no answer generation, no
  citations returned to a caller.
- **No authentication or authorization.** No Cognito integration; every endpoint is open.
- **No persistence.** No database, no ORM models, no migrations.
- **No AWS integration of any kind.** Every AWS service in the stack table is planned,
  not wired.
- **No frontend.**
- **No infrastructure as code.**
- **No metrics endpoint and no evaluation module.** The readiness probe currently
  reports an empty check list because there is nothing to check yet.

## Security notes

- No credentials are committed. `.env` is git-ignored; `.env.example` contains only
  defaults and is safe to commit.
- All configuration arrives through environment variables, matching how ECS, Lambda and
  App Runner inject configuration and secrets.
- Internal exception detail is logged server-side and never returned in a response body.
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
