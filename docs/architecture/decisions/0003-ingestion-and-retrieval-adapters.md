# ADR 0003 — Ingestion pipeline, retrieval adapters and a polling worker

- **Status:** accepted
- **Phase:** 3
- **Date:** 2026-01-01

## Context

Phase 3 turns stored documents into retrievable knowledge. That means parsing four
formats, splitting text into passages that keep their structure, turning passages into
vectors, holding those vectors somewhere searchable, and doing all of it *after* the
upload request has been answered. Every one of those steps needs an adapter that is
local today and AWS-hosted later.

## Decisions

### 1. Ingestion runs on a polling worker, not on a request background task

The obvious implementation is `BackgroundTasks`: the upload handler schedules ingestion
and returns. It does not work here, and the reason is worth recording because it is not
obvious.

FastAPI runs a response's background tasks **before** it exits the request's dependency
generators. So a task scheduled from a handler runs while the request's transaction is
still open. Observed directly with engine-level transaction logging on a single upload:

```
[  0.269] engine.begin       <- the upload's INSERT, uncommitted
[  0.272] engine.begin       <- the background task's own session
[  0.273] engine.rollback    <- LookupError: the document is not visible yet
[  0.336] engine.rollback    <- database is locked: the request still holds the write lock
[  0.344] engine.commit      <- the request transaction finally commits
```

The document stayed `pending` for ever, and every upload paid SQLite's five-second busy
timeout waiting for a lock it could never take. A test that only asserts the upload
response does not notice any of this.

Ingestion therefore runs on `IngestionWorker`: a thread started with the application
that polls for documents in `pending` and processes them with sessions of its own.
Uploads and `POST .../reprocess` only record state; nothing in a request waits for
parsing.

Consequences:

- Ingestion is fully decoupled from the request. There is no shared transaction, no
  lock contention, and no chance of a half-visible row.
- The worker assumes a single process. Two uvicorn workers would both poll the same
  documents, which is precisely the problem a queue solves; claiming work atomically is
  the AWS consumer's job.
- Tests disable the worker and call `run_pending()` directly, so no test depends on
  timing. One dedicated test runs the real thread and waits for the result.

### 2. Parsers keep structure, and admit what they do not do

Parsing is dispatched on the file extension and returns blocks that carry whatever
structure the format provides: the page number for a PDF (through `pypdf`), the heading
path for Markdown. That metadata is the difference between a citation and a quote.

Deliberate limits, all recorded rather than hidden:

- **No OCR.** A scanned PDF has no extractable text; the document fails with that
  reason instead of indexing an empty string.
- **No CommonMark AST.** Markdown is split on ATX headings and otherwise kept as
  written, because parsing inline markup only to discard it buys nothing. The one
  concession is that a heading line loses its `#` markers so they do not become
  embedding noise.
- **Non-UTF-8 text is decoded with replacement**, and the document records that it
  happened rather than silently mangling the characters.

### 3. Chunking is character-based, boundary-aware and offset-exact

Windows are measured in **characters**, not model tokens. Counting tokens requires the
tokenizer of the model that will consume the text, which belongs to the generation
adapter and arrives with it; the approximation is documented in the configuration
reference instead of being papered over. Windows prefer a paragraph break, then a line
break, then a sentence, then a space, and only fall back to a hard cut.

Every chunk records its page, its heading path, its position in the document and the
character offsets it came from, with the offsets trimmed to bound the stored content
exactly. Chunk content is preserved verbatim: nothing is summarised or rewritten.

### 4. Embeddings sit behind a port with an explicitly lexical local adapter

`EmbeddingModel` separates document and query embedding, because real providers often
treat them differently. The local adapter is `HashingEmbeddingModel`: hashed term
frequencies, sublinear weighting, L2-normalised, hashed with `blake2b` rather than the
built-in `hash` so that vectors persisted by one process still line up in the next.

It is a **lexical** model and is named, documented and reported as such. It matches
shared vocabulary, knows nothing about meaning or synonyms, and exists so the pipeline
runs offline and deterministically. The Amazon Bedrock embedding model implements the
same port. No claim of semantic retrieval quality is made anywhere in this repository.

### 5. The vector index stores identifiers and vectors; the corpus stays in the database

`VectorStore` indexes `(chunk_id, document_id, knowledge_base_id, vector)`. Chunk text
lives in the `chunks` table, so a search result resolves back to its passage instead of
the index keeping a second copy of the corpus that can drift.

`InMemoryVectorStore` scores every vector with cosine similarity — brute force,
dependency-free and exact, which lets tests assert ordering rather than approximation.
A lock guards it because the worker writes while requests search. Search returns the
best candidates regardless of score: deciding that nothing is relevant enough is a
retrieval policy, not an index concern.

### 6. Embeddings are stored with the chunk

The index is in memory, so a restart would otherwise leave documents reported as
`ready` that nothing can retrieve. Storing the vector beside the text makes the index
pure derived state: `rebuild_vector_index` repopulates it at startup from the database
without re-embedding the corpus, and `recover_interrupted` returns documents left in
`processing` by a crash to the queue.

Storing a JSON array of floats per chunk is a deliberate local compromise, not a
design for scale. It is also why changing `APP_EMBEDDING_DIMENSIONS` invalidates every
stored vector and fails loudly at startup instead of silently scoring nonsense.

### 7. `READY` means indexed, and nothing else does

The pipeline holds one invariant: a document is `ready` if and only if its chunks are
stored and indexed. A failure clears both and records a reason. `reprocess` clears both
before queueing the next run, so no caller ever sees a document reported as pending
whose previous passages are still retrievable.

The reason a caller sees is drawn from a whitelist of messages that are safe to
publish — a parse failure, an unreadable object, or the exception *type* of anything
else. Internal detail is logged, not returned.

## Alternatives considered

- **`BackgroundTasks` for ingestion.** Rejected; see decision 1. Keeping it would have
  meant committing the upload inside the handler purely to make the row visible to a
  second execution context, which is a worse-kept secret than an explicit worker.
- **Synchronous ingestion inside the upload request.** Rejected: a large PDF would hold
  the request open for the whole pipeline, and the status column would be decorative.
- **Celery or RQ for the local worker.** Rejected as the wrong weight for a
  single-process laptop run: it adds a broker and a second process to supervise before
  anything needs distributing. The port boundary is what makes the swap cheap later.
- **A test double for embeddings during ingestion.** Rejected: it would leave the real
  adapter untested end to end. The hashing model is fast and deterministic, so the
  tests use it directly.
- **Storing the embedding as a binary blob (or `numpy.float32`).** Rejected for now:
  JSON keeps the schema readable and diffable, and a native `vector` column replaces it
  with pgvector in the AWS phase.
- **Splitting on tokens with `tiktoken` or a model tokenizer.** Rejected: it would bind
  the chunker to one provider's tokenizer before a provider has been chosen.
- **A relevance threshold inside the vector store.** Rejected: a store that decides what
  counts as irrelevant cannot be reused by a caller with different needs.
- **Chunk-level de-duplication or overlap trimming.** Not implemented, and not claimed:
  overlap means the same sentence can appear in two chunks, which is the point.

## Follow-up work

- Phase 4 adds retrieval and generation on top of these ports, including the relevance
  threshold and reranking that decision 5 leaves to the caller.
- Phase 5 measures retrieval quality; until then no quality claim is made.
- Phase 7 replaces the worker with a queue and a Lambda consumer, the hashing model with
  Bedrock embeddings, and the in-memory index with OpenSearch or pgvector.
