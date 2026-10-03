# ADR 0005 — Observability and the evaluation module

- **Status:** accepted
- **Phase:** 5
- **Date:** 2026-01-01

## Context

Phase 4 gave every answer a trace, which makes one answer diagnosable. It does not make the
platform's behaviour measurable: a trace is read one request at a time, and every claim
about retrieval or answer quality was still an assertion. Phase 5 has to supply both — the
aggregate numbers an operator watches, and the measurement that decides whether a claim
holds.

The constraint that shapes the second half is that a metric may only exist if it is
implemented correctly. The evaluation module therefore computes standard
information-retrieval metrics from labels a caller supplies, and computes nothing that
would need a judgement it does not have.

## Decisions

### 1. Metrics are per-process counters and a bounded latency window

`MetricsRegistry` holds integers keyed by name and a fixed-size window of recent latency
samples per stage, exposed at `GET /api/v1/metrics`. It is deliberately not a time-series
store: unbounded sample retention is a memory leak in a long-running process, and the
deployment's CloudWatch metrics are the record that survives restarts and spans replicas.
`window`, `observed` and `retained` are reported alongside each summary so a reader can see
when the window is the limiting factor rather than the traffic.

Latency percentiles are **nearest-rank**. An interpolating definition can answer with a
value between two observations, or below the smallest one, which would imply a precision
the measurement does not have.

### 2. A stage that never ran has no latency, not a zero one

If nothing reaches the generator, there is no `generation` latency — not `0.0 ms`. This is
the same principle as `insufficient_evidence`: an absent measurement and a measurement of
nothing are different facts, and conflating them hides a broken pipeline behind a fast one.
The metrics suite asserts it, which turns the Phase 4 invariant into something an operator
can see: after a question with no evidence, `query.insufficient_evidence` rose and no
`generation` sample was recorded.

Token counters follow the same rule: the extractive adapter reports no usage, so no
`generation.input_tokens.total` counter exists rather than one that understates the model.

### 3. Labels are route templates, without the API version prefix

A counter labelled with a concrete path would let any caller invent unbounded metric series
by inventing identifiers. Labelling with the matched route template fixes the cardinality at
the size of the route table, and an unmatched request shares one `http.route.unmatched`
bucket.

The label is the template as the router declares it (`/knowledge-bases/{knowledge_base_id}`),
which does not include the version prefix, because the prefix is a mounted path rather than
part of the route. That is a feature: changing `APP_API_V1_PREFIX` does not split every
counter in half.

One consequence is inherent and is asserted rather than left to be discovered: the request
that reads `/metrics` is recorded as a request before the snapshot is taken and as a
response after it, so a snapshot always shows the read itself as in flight.

### 4. The evaluation dataset carries its own corpus

`POST /api/v1/evaluations` takes the corpus with the questions. The run creates a knowledge
base of its own, ingests the corpus into it, asks every question through the same query
service the API serves, scores the results and removes the knowledge base before returning.

Three things follow, and all three are why it is built this way:

- Two runs of the same dataset are comparable. If evaluation scored whatever happened to be
  ingested, the numbers would depend on platform state and would not be reproducible.
- Nothing already in the platform can influence the numbers, and nothing the evaluation
  ingests outlives it. A leftover corpus would be searchable through the API and would make
  the next run's numbers depend on the last one's leftovers.
- A dataset is a file that can be reviewed, versioned and diffed. The sample lives at
  `evaluation/datasets/sample.json`, and the test suite runs that file as committed, so a
  dataset that stops being runnable fails the build instead of misleading a reader.

### 5. Labels are a document and a snippet, never a chunk identifier

Chunk identifiers are generated at ingestion time and change when a document is re-ingested,
so a dataset written against them would rot silently — the numbers would change while the
file stayed the same, which is the worst possible failure for a measurement.

A label is therefore a document name plus a snippet, resolved against the ingested chunks at
run time. A snippet that falls inside two overlapping chunks legitimately resolves to both.
A snippet that resolves to nothing is reported in `issues` and leaves the question
unscorable, rather than being scored as a retrieval miss: a missing label is a defect in the
dataset, and counting it as a quality failure would blame the platform for the dataset's
mistake.

### 6. Only metrics that follow from the labels are computed

Implemented: `recall_at_k`, `precision_at_k`, `hit_rate_at_k`, `mrr`, `ndcg_at_k` (binary
gains, `log2(rank + 1)` discounting, ideal ranking from every labelled-relevant chunk), and
`citation_precision` / `citation_recall` over the chunks an answer cited.

Not implemented, and not pretended: **no faithfulness, groundedness or hallucination
metric**. A question is scored by whether the chunks the answer cited are the ones the labels
mark relevant, which is a fact about the citation list. Whether the prose is faithful to
those chunks needs human or model judgement, and this module has neither; a lexical overlap
heuristic standing in for it would be a number with no meaning, which is worse than an
absent one.

Two conventions are stated because they change the numbers: `precision_at_k` divides by `k`,
not by the number of results returned, so a corpus too small to fill `k` slots caps precision
accordingly; and a metric whose denominator is zero raises instead of returning zero, so an
unanswerable question has *no* recall rather than a recall of `0.0`. Rates with no
observations are reported as `null` for the same reason — a dataset with no unanswerable
question has not demonstrated that the platform abstains.

### 7. The threshold a run used is part of its results

The request may override `k` and `min_score`, and both are reported back with the report. A
number produced under a different retrieval policy than the one the server serves cannot be
read without knowing the policy, and comparing thresholds is precisely what this endpoint is
for.

### 8. The run is synchronous, and its bounds are the request's bounds

An evaluation ingests its corpus and answers every question before returning, so the payload
is capped (25 documents, 100 questions, 100 000 characters per document) and the limits are
part of the API contract. Evaluating a real corpus belongs in a batch job with progress
reporting; pretending a request can do it is how a demo becomes a production incident.

## The measurement this phase produced

The sample dataset was written to be small and obvious: five runbook documents, five
questions whose labels quote the corpus, and one question about the company holiday schedule
that the corpus does not answer. With the local lexical embedding model and the default
threshold of `0.1`, the run reports:

```
recall_at_k 1.0   precision_at_k 0.2   hit_rate_at_k 1.0   mrr 1.0   ndcg_at_k 1.0
answered 6/6      answerable_answered 1.0      unanswerable_abstained 0.0
citation_precision 0.26   citation_recall 1.0
```

`precision_at_k` of 0.2 is the definition doing its work rather than a retrieval problem:
each question has one relevant chunk, and precision divides by `k = 5`. The number worth
attention is `unanswerable_abstained 0.0`: **the platform answered a question the corpus does
not answer.** Measuring the per-question top scores explains why:

| question | answerable | best candidate score |
|---|---|---|
| encryption-at-rest | yes | 0.6940 |
| sev1-acknowledgement | yes | 0.6080 |
| snapshot-retention | yes | 0.5015 |
| production-access-approval | yes | 0.4186 |
| **holiday-schedule** | **no** | **0.3146** |
| credential-rotation | yes | **0.2578** |

The unrelated question scores **above** a genuinely relevant one. There is no threshold that
refuses it and keeps every answerable question, because the two ranges overlap: the hashing
embedding model's score measures shared vocabulary, and function words are shared vocabulary.
This is the model that Phase 4 documented as lexical rather than semantic, now measured
rather than asserted.

A stricter threshold makes the trade-off explicit, and the endpoint reports both sides of it.
At `min_score = 0.35`:

```
answerable_answered 1.0 -> 0.8      unanswerable_abstained 0.0 -> 1.0
citation_precision  0.26 -> 0.875   recall_at_k 1.0 -> 0.8
```

Buying the abstention costs one answerable question and lowers recall; it also makes the
citations substantially cleaner, because a higher threshold keeps the irrelevant passages out
of the context. Which side of that trade a deployment wants is a product decision, and the
point of this phase is that it can now be decided from numbers instead of intuition.

What this does **not** establish: that a threshold can be tuned into a relevance filter for
this model, and that the platform is safe from unsupported answers in general. The
`insufficient_evidence` outcome is reached only when nothing clears the threshold at all. With
the extractive generator the harm of a false positive is a verbatim passage that does not
answer the question; with a generative model the same input is a prompt containing irrelevant
context, which is exactly the situation in which a model invents something. Closing that gap
needs semantic embeddings (Phase 7) and a re-measurement, not a different default.

The same dataset was also used to settle the reranker question ADR 0004 left open, and it
could not settle it. With `APP_RERANK_ENABLED=true` every reported number is identical to the
unranked baseline — `recall_at_k 1.0`, `mrr 1.0`, `ndcg_at_k 1.0`, `citation_precision 0.26` —
because the baseline already ranks the relevant chunk first for all five questions, so the
metrics are at their ceiling and there is no headroom in which a reranker could show a gain.
An inconclusive measurement is not a positive one: the reranker stays disabled, and the
endpoint is how the question gets answered on a dataset whose baseline is not already perfect.

## Alternatives considered

- **Prometheus or CloudWatch export in this phase.** Deferred to Phase 7 with the rest of the
  AWS adapters. A JSON snapshot is what a local run and the UI in Phase 6 need, and an
  exporter added before there is anything to export would be untested code.
- **Keeping all latency samples.** Rejected: unbounded growth in a long-running process, and
  the interesting percentiles are about recent behaviour.
- **Interpolated percentiles.** Rejected; see decision 1.
- **Labelling metrics with the full URL path.** Rejected; see decision 3.
- **Recording a zero for a stage that did not run.** Rejected; see decision 2.
- **Persisting evaluation runs so they can be compared over time.** Not implemented. A run is
  a result, not a resource: it is self-contained, and storing it would need retention,
  ownership and cleanup decisions that a phase about measurement should not prejudge.
- **An LLM judge for answer faithfulness.** Not implemented. It would need a model that may
  not be reachable, credentials, and its own evaluation to establish that the judge agrees
  with a human; claiming a faithfulness score from it without that would be the clearest
  possible exaggeration.
- **Scoring against whatever is already ingested.** Rejected; see decision 4.
- **Chunk identifiers as labels.** Rejected; see decision 5.
- **Reporting `precision_at_k` as `matched / returned`.** Rejected: that is a different
  metric, and renaming a standard one to make a small corpus look better is how metrics stop
  meaning anything.

## Follow-up work

- Phase 6 surfaces the metrics and an evaluation run in the UI.
- Phase 7 replaces the embedding model and re-measures: the sample's overlapping score ranges
  are the specific claim to re-test, and the evaluation endpoint is how.
- A dataset on which the unranked baseline is *not* perfect is needed before the reranker can
  be judged; the sample is too easy to decide it.
- Retrieval metrics with graded relevance, and multi-run comparison, are worth adding when
  there is a labelled corpus large enough to need them.
