# ADR 0001 — Backend foundation for the RAG platform

- **Status:** accepted
- **Phase:** 1
- **Date:** 2026-01-01

## Context

The platform must end up as a production-style AWS application: S3 for document
storage, Bedrock for embeddings and inference, a vector index, Cognito for
authentication, CloudWatch for observability, Secrets Manager for secrets, and
Terraform for infrastructure. At the same time the repository has to be runnable and
testable on a laptop without provisioning a single AWS resource, and later phases must
be able to swap in real AWS adapters without rewriting the domain logic.

Phase 1 therefore establishes the backend foundation and the seams that every later
phase plugs into. The decisions below are the ones that would be expensive to reverse.

## Decisions

### 1. Ports and adapters, with the AWS adapter as a first-class implementation

External capabilities (object storage, embedding provider, vector index, language model,
secret resolution) will be expressed as narrow interfaces owned by the domain — typed
`Protocol`s — and implemented twice: once against AWS and once as a local adapter for
development and tests.

Consequences:

- The domain and API layers never import `boto3`.
- Local development runs with no cloud dependency; the AWS path stays a real
  implementation rather than a mock.
- Tests assert against the behaviour of the port, not against a specific backend.

This is scheduled for the phases that introduce each capability (Phase 2 for storage,
Phase 3 for embeddings and the vector index, Phase 4 for inference, Phase 7 for the AWS
implementations). Interfaces are introduced when their first consumer exists, so that no
empty module is committed.

### 2. Configuration is typed and environment-driven

`app.core.config.Settings` is a `pydantic-settings` model reading `APP_*` environment
variables and an optional `.env` file. Unknown `APP_*` variables are ignored; invalid
known values fail fast at startup.

Consequences:

- The same image runs in every environment with no code change, matching how ECS,
  Lambda, App Runner and Terraform inject configuration.
- Configuration errors surface at boot instead of at first use.
- No configuration file is ever committed, so secrets cannot leak through Git.

### 3. Settings are injected into the application, not imported by it

`create_app(settings)` stores the resolved settings on `app.state`; routes receive them
through the `get_app_settings` dependency.

Consequences:

- Tests build an application with their own settings and never depend on the ambient
  environment.
- Multiple application instances with different configuration can coexist in one
  process, which keeps test isolation cheap and makes future multi-tenant work possible.

### 4. Structured logging with request correlation from the first commit

`structlog` renders every record as JSON (default) or as console output. A
`ContextVar` holds the request id; the logging chain injects it into every record, and
the standard-library root logger is routed through the same renderer so third-party
records are structured too.

Consequences:

- A CloudWatch Logs Insights query can filter on `request_id` across the access record,
  service logs, and library logs.
- Structured fields are added as behaviour is added; no reformatting pass is needed in
  Phase 5.
- Uvicorn's own logging configuration and access log are disabled in `python -m app`,
  because the middleware already emits one structured access record per request.

### 5. One error envelope for every failure

`AppError` and its subclasses carry a stable machine-readable `code` and an HTTP
`status_code`. Handlers translate application errors, framework HTTP errors, validation
failures and unexpected exceptions into the same envelope, which always includes the
request id. Unexpected exceptions are logged with a traceback and reported to the caller
as a generic 500.

Consequences:

- Clients implement error handling once.
- Error codes become a stable part of the public contract and can be asserted in tests.
- Internal detail cannot leak through an error response.

### 6. Local vector storage is an in-memory adapter behind a port

Retrieval will be defined by a vector-index port. The local implementation will keep
vectors in memory; AWS deployments will use OpenSearch Serverless or PostgreSQL with
pgvector behind the same port.

Consequences:

- Local setup needs no container, which keeps the repository immediately runnable.
- Retrieval tests are deterministic and fast.
- The in-memory adapter is a *development* backend: it is not durable and will be
  documented as such rather than presented as production storage.

### 7. Repository layout mirrors the domain, not the framework

```
app/api        transport: routes, dependencies, middleware, error mapping
app/core       configuration, request context, logging
app/schemas    wire contract
app/services   use cases (added with the first use case)
app/repositories  persistence ports and adapters (added with the first entity)
app/integrations/aws  AWS adapters (added in Phase 7)
app/rag | app/ingestion | app/evaluation | app/observability
```

Consequences:

- A reviewer can find retrieval logic without reading the HTTP layer.
- Directories appear when they contain real code; the repository never carries empty
  placeholder packages.

## Alternatives considered

- **A single `services.py` module.** Rejected: it becomes the giant service file the
  project explicitly avoids, and it hides the boundaries that later phases depend on.
- **Wire the AWS SDK first and mock it in tests.** Rejected: tests would assert against
  mocks of our own code, the repository would not run without AWS, and local development
  would need real infrastructure.
- **Adopt a RAG framework (LangChain or similar).** Rejected: it obscures the retrieval,
  prompting and citation logic that this project exists to demonstrate.
- **Microservices from the start.** Rejected as unnecessary complexity for the problem;
  the platform is one service plus asynchronous ingestion work.
- **`os.environ` reads scattered through the code.** Rejected: untyped, untested, and it
  defeats startup validation.

## Follow-up work

- Phase 2: storage port plus local filesystem adapter; knowledge base and document
  endpoints.
- Phase 3: ingestion pipeline and the vector index port with an in-memory adapter.
- Phase 4: retrieval, reranking abstraction, Bedrock-backed generation, citations.
- Phase 5: metrics and the evaluation module.
- Phase 7: AWS adapters, Terraform, and Cognito-backed authentication and authorization.
