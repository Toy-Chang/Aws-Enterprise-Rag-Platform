# ADR 0002 — Relational metadata, a storage port, and synchronous request handling

- **Status:** accepted
- **Phase:** 2
- **Date:** 2026-01-01

## Context

Phase 2 adds the first real state to the platform: knowledge bases, uploaded
documents, and the document content itself. This forces three decisions that later
phases inherit — how relational metadata is persisted, how document content is
abstracted away from its backend, and whether request handling is synchronous or
asynchronous.

The constraints from ADR 0001 still apply: the repository must run on a laptop with
no cloud dependency, AWS must remain a first-class implementation rather than a mock,
and the architecture must not be contaminated by local-development shortcuts.

## Decisions

### 1. Metadata is relational, persisted with SQLAlchemy; SQLite locally

Knowledge bases and documents are strongly relational (a knowledge base owns many
documents, documents are queried by parent and by status), and every later phase adds
more relational structure — chunks, evaluation runs, query traces. The metadata layer
is therefore SQLAlchemy 2.0 with a declarative model, and the database URL is
configuration rather than code.

SQLite is the local default because it needs no container, no daemon and no
credentials: `python -m app` works on a clean checkout. The AWS deployment points
`APP_DATABASE_URL` at PostgreSQL, which the same repositories and models already
target.

Consequences:

- Local development has zero setup cost, and the test suite runs against a real
  database engine rather than an in-memory fake.
- `sqlite` specifics are confined to `app.core.db`: the `check_same_thread` connect
  argument and a `PRAGMA foreign_keys=ON` listener, because SQLite leaves foreign key
  enforcement off by default.
- Schema creation is `Base.metadata.create_all` at startup. That is honest for a
  schema this young but it is not a migration story; Alembic replaces it before the
  service holds data worth preserving, and this ADR is the record of that debt.
- A single namespace of knowledge base names is enforced at the service layer.
  Scoping names per tenant arrives with authentication.

### 2. Document content sits behind a port, with the filesystem adapter shipping now

`DocumentStorage` is a `typing.Protocol` owned by the repository layer. Phase 2 ships
`LocalFileSystemStorage`; the Amazon S3 adapter implements the same two methods.

Consequences:

- Services depend on the port, so nothing in the domain branches on which backend is
  configured.
- The port is deliberately minimal — `save` and `delete`, the operations Phase 2
  actually performs. Reading content back is added with the ingestion pipeline, which
  is its first consumer, rather than speculatively now.
- Storage keys are derived from server-generated identifiers and validated against the
  storage root, so a caller cannot influence the path that is written.
- Deletion across the database and the object store is not atomic. Content is removed
  first and storage failures are logged rather than raised: metadata is the source of
  truth, so the outcome of a partial failure is unreferenced content (reclaimable) and
  never a row pointing at content nobody can read.
- An upload writes content before metadata for the same reason. A failure between the
  two leaves content that no row references.

### 3. Request handling is synchronous

Endpoints are plain `def`, so FastAPI runs them in a worker thread, and services use a
synchronous SQLAlchemy `Session`. `python-multipart` supplies the upload parsing.

Consequences:

- One consistent execution model, which keeps the code and the failure modes easy to
  reason about, and keeps the test suite deterministic.
- Database sessions are never held across an `await`, so the classic "sync session in
  an async handler" defect cannot occur.
- Blocking work does not stall the event loop, because it happens in the thread pool.
- If a later phase adopts a genuinely asynchronous client (a streaming Bedrock call,
  for instance), that decision is made then, on its own merits, rather than guessed at
  now.

### 4. Transaction boundaries sit at the edge of the request

`get_db` yields a session, commits when the handler returns, and rolls back on any
exception. Services stage changes and may `flush` to obtain generated values, but they
never commit.

Consequences:

- A handler that fails part-way leaves no partial writes, without every service having
  to remember to roll back.
- Services stay free of transaction management, so they can be composed inside a single
  unit of work.

### 5. Errors are raised as domain types from `app.core.errors`

The `AppError` hierarchy moved out of the web layer in this phase. Services raise
`NotFoundError`, `ConflictError`, `UnsupportedMediaTypeError` and friends; the HTTP
handlers in `app.api.errors` translate them into the response envelope.

Consequences:

- The domain has no dependency on FastAPI, which keeps it portable and directly
  testable.
- New failure modes are added once, as a typed error with a stable code, instead of as
  ad-hoc status codes at each call site.

## Alternatives considered

- **In-memory repositories.** Rejected as the primary store: knowledge bases and
  documents are relational data that outlives a process, and the second phase is the
  right time to establish that rather than to build a fake that is thrown away.
- **PostgreSQL with pgvector from the start.** Rejected for Phase 2: it makes local
  setup depend on Docker before a single query is needed. The vector index port and its
  storage decision belong to the retrieval phase.
- **Async SQLAlchemy with `aiosqlite`.** Rejected for now: it doubles the session and
  testing surface to buy concurrency the current workload does not need, and the
  thread-pool model already keeps the event loop free.
- **Storing document content in the database.** Rejected: it fights the reason object
  storage exists, and it would have to be undone in the AWS phase.
- **A generic `Storage` interface with download, listing and metadata operations now.**
  Rejected as speculative: only `save` and `delete` have callers today.
- **Soft-delete / archive flags for documents.** The product requirement mentions
  "delete/archive". A hard delete is what is implemented, and no archive column is
  claimed; archive semantics arrive with the retention requirements that motivate them.

## Follow-up work

- Phase 3 adds the ingestion pipeline, extends `DocumentStatus`, adds the vector index
  port, and gives `DocumentStorage` its first read consumer.
- Alembic migrations replace `create_all` before any deployment holds real data.
- Phase 7 adds the S3 storage adapter and moves `APP_DATABASE_URL` to PostgreSQL.
