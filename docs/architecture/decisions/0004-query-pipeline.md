# ADR 0004 — The query pipeline: retrieval, evidence and grounded answers

- **Status:** accepted
- **Phase:** 4
- **Date:** 2026-01-01

## Context

Phase 3 made documents searchable. Phase 4 has to answer questions from them, and the
requirement that shapes every decision below is the enterprise one: an answer must be
traceable to the evidence it came from, and when there is no evidence the platform has
to say so. A fluent answer that cannot be traced is worse than no answer at all.

## Decisions

### 1. Retrieval returns candidates; deciding relevance is a separate policy

`InMemoryVectorStore.search` returns the best matches whatever their score. The
threshold that decides whether something counts as evidence lives in `RetrievalService`
(`APP_RETRIEVAL_MIN_SCORE`, overridable per request), because "relevant enough" depends
on the embedding model and on the question, not on the index.

This is what makes the empty-answer case reachable at all. If the index decided
relevance, a caller could not ask for a stricter or a looser standard, and the
platform's answer to "I don't know" would be a fixed constant buried in an adapter.

The trace reports both counts, because "the index found nothing" and "everything found
was below the threshold" are different problems:

```
candidates: 8      # what the index returned for this call
above_threshold: 3 # what cleared min_score
used: 3            # what retrieval selected
```

Those counts describe *this call*: without a reranker, retrieval asks the index for
exactly `top_k` passages, so a small `top_k` reports a small candidate count even in a
large corpus. With a reranker it asks for `top_k × APP_RETRIEVAL_CANDIDATE_MULTIPLIER`,
so that reranking has a choice rather than a single option.

### 2. "I don't know" is decided before generation, not by a prompt

If no passage clears the threshold, `QueryService` returns
`outcome: "insufficient_evidence"` with `answer: null` and never calls the generator.
No prompt is asked to refuse politely, because a prompt instruction is a request, not a
guarantee — and the failure mode of ignoring it is exactly the invented answer this
platform exists to avoid.

The response says which happened in a field of its own rather than in prose, so a client
can act on it:

```json
{"outcome": "insufficient_evidence", "answer": null, "citations": [], "usage": {"input_tokens": null, "output_tokens": null}}
```

### 3. Citations come from the passages, not from the model's output

The prompt asks the model to mark statements with `[1]`, `[2]` and so on, but the
platform does not parse those markers back out to decide what was cited. The citation
list *is* the set of passages the context was built from, in marker order, each with its
document, heading path, page, chunk id, similarity and rerank score.

Consequences:

- A model that ignores the markers, or marks the wrong passage, cannot corrupt the
  citation list — at worst its prose does not line up with the evidence, which is
  visible to the reader.
- A citation always resolves to a stored chunk, because passages are read from the
  database by id rather than from the index.

### 4. Generation is a port; the local adapter is extractive and says so

`AnswerModel` is implemented by:

- **`ExtractiveAnswerModel`** (`kind: "extractive"`, the default). It returns the
  retrieved passages verbatim under their markers. It is not a language model and cannot
  invent content, which makes the whole pipeline — retrieval, threshold, context,
  citations, trace — runnable and testable offline. A test asserts that a passage quoted
  in the answer is byte-for-byte the stored chunk.
- **`BedrockAnswerModel`** (`kind: "generated"`) for Amazon Bedrock's Converse API. Its
  client is injected, so the request and response mapping is tested against a stub
  without an AWS account, and `boto3` is imported only when the adapter builds its own
  client — the base install does not pull in the AWS SDK (`pip install -e '.[aws]'`).

The response therefore carries `answer_kind`, so a caller is never left guessing whether
a paragraph was written by a model or copied from a document. Which adapter is used is
decided in `create_app` from `APP_GENERATION_PROVIDER`, so no service branches on it.

Honest scope of the Bedrock adapter: **it has never been exercised against a live
endpoint from this repository**, because that needs AWS credentials and a model the
account may not have access to. What is verified is the request it builds, the response
it parses, the failures it translates, and that it is selected by configuration.

### 5. Reranking is a port with a real implementation, and it is off by default

`Reranker` is implemented by `LexicalOverlapReranker`, which re-scores candidates by the
fraction of the question's distinct terms they contain, with ties broken by the
retrieval score and then by chunk id so the order is reproducible.

It is not a learned cross-encoder, and it is **disabled by default**. Enabling it by
default would be a quality claim, and nothing in this repository has measured that it
improves anything: it re-weights the same lexical signal the local embedding already
uses. Phase 5 measures it against the unranked baseline and that measurement decides the
default. Until then `APP_RERANK_ENABLED=true` turns it on explicitly.

### 6. The context is a character budget, and citations match what fit

`build_context` renders whole passages only, dropping those that do not fit rather than
cutting them in half, so a citation never points at half a sentence. The exception is
the first passage: if it alone exceeds the budget it is truncated, because returning an
empty context would throw away a retrieval that did find something.

The returned passages are the ones actually rendered, and the citation list is built
from those — so `citations` always matches the context the generator read. The character
budget is a deliberate approximation of a token budget; token counting arrives with the
generation adapter that knows its tokenizer.

### 7. A failed generator is an upstream failure, not a bad request

`GenerationFailedError` maps to **502 `GENERATION_FAILED`**: the caller asked something
the platform accepted, and the model behind the port did not answer. Credentials,
throttling, an unknown model id and a network failure are all the same thing to the
caller, and the detail is kept in the raised error's cause chain.

That change exposed a gap in the Phase 1 error handler worth recording: deliberate
application errors were logged without `exc_info`, so a 502 recorded *what* failed but
not *why*. Server-side failures (5xx) are now logged with their cause chain, while 4xx
failures stay a warning without a traceback, since a rejected request is not a defect in
this service. Both behaviours have tests.

### 8. Every answer carries a trace

`trace` reports each stage's counts and duration, plus the request id, the reranker, the
generator, the model identifier and the context size. This is what makes a wrong answer
diagnosable: whether retrieval found nothing, whether the threshold rejected it, whether
the budget kept a passage out, or whether the model ignored what it was given.

Durations come from `time.perf_counter` and are reported in milliseconds. Retrieval and
generation are timed separately, and `retrieval.used` deliberately counts what retrieval
selected rather than what the answer cited — a test caught the two being conflated, and
the distinction is now documented on the field.

## Alternatives considered

- **Letting the index apply the threshold.** Rejected; see decision 1.
- **Asking the model to say "I don't know".** Rejected; see decision 2.
- **Parsing `[n]` markers out of the model's answer to build citations.** Rejected: it
  makes the citation list only as trustworthy as the model's formatting.
- **Hiding the extractive generator behind the same wording as a model.** Rejected: it
  would make an offline run look like a generative one. `answer_kind` exists to prevent
  exactly that misreading.
- **Shipping a `BedrockEmbeddingModel` in this phase to make retrieval semantic.**
  Deferred to Phase 7 with the other AWS adapters, so that the local pipeline stays
  deterministic and testable, and so that no semantic quality is claimed before there is
  an evaluation to support it.
- **A relevance threshold inside the vector store or a hard-coded score cutoff.** See
  decision 1.
- **Conversation history, query rewriting or multi-turn context.** Not implemented. The
  endpoint answers one question at a time; adding turns changes retrieval and evaluation
  and is not something to fake.
- **Caching answers.** Not implemented: a cache would make the trace describe a
  retrieval that did not happen, and there is nothing yet to measure whether it pays.
- **Streaming the answer.** Not implemented. The extractive adapter has nothing to
  stream, and a real streaming design belongs with the client that consumes it.
- **Deduplicating near-identical passages.** Not implemented and not claimed. Chunk
  overlap means the same sentence can legitimately appear in two retrieved passages, and
  a query can match two documents that quote each other.

## Follow-up work

- Phase 5 measures retrieval quality — including whether the reranker earns its place —
  and adds the metrics that make these traces aggregable.
- Phase 6 surfaces the answer, the citations and the trace in the UI.
- Phase 7 replaces the hashing embedding model with Bedrock embeddings, the in-memory
  index with OpenSearch or pgvector, and the worker with a queue and a consumer.
