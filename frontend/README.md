# Frontend — operator UI

React + TypeScript UI for the AWS Enterprise RAG Platform backend. It is the Phase 6
deliverable: four screens that exercise everything the API exposes, including the parts a
"chat with documents" demo usually hides — the citations, the per-stage trace, the metrics
snapshot and the evaluation report.

It is an **operator UI**, not a consumer app: it shows what the pipeline did, which documents
were indexed, what a retrieval threshold costs, and what the platform has actually recorded.

## Running it

The UI talks to the backend through a dev-server proxy, so the backend has to be running
first and there is no CORS configuration to get wrong.

```bash
# terminal 1 — the API on 127.0.0.1:8000
cd backend
.venv/bin/python -m app

# terminal 2 — the UI on 127.0.0.1:5173
cd frontend
pnpm install
pnpm dev
```

Open <http://127.0.0.1:5173>. Putting the backend somewhere else is one line in
[`vite.config.ts`](vite.config.ts) (`backendTarget`).

| Script | What it does |
|---|---|
| `pnpm dev` | Vite dev server, proxying `/api` and `/health` to the backend |
| `pnpm build` | Production build into `dist/` |
| `pnpm preview` | Serve the built `dist/` locally |
| `pnpm typecheck` | `tsc --noEmit`, strict, with `noUncheckedIndexedAccess` |
| `pnpm test` | Vitest + Testing Library, once |
| `pnpm test:watch` | The same suite in watch mode |

## The screens

- **Knowledge bases** (`/`) — list, create, delete. A duplicate name surfaces the backend's
  `409 CONFLICT` with its own message rather than a generic failure.
- **One knowledge base** (`/knowledge-bases/:id`) — two tabs.
  - *Documents*: upload, status (`pending` → `processing` → `ready` / `failed` with the
    failure reason), passage counts, reprocess, delete. The list refreshes itself while
    anything is being ingested, and stops when nothing is.
  - *Ask a question*: the answer with its citations and a collapsible trace, newest first.
    `top-k` and `min_score` can be overridden per question, which is how the retrieval
    policy is explored rather than guessed at.
- **Evaluation** (`/evaluations`) — run a labelled dataset and read the report: retrieval
  metrics, answer behaviour, latency, dataset problems and a per-question table.
- **Metrics** (`/metrics`) — counters grouped by prefix and latency summaries with
  `observed` / `retained`, over a bounded per-process window.

The header shows whether the API is actually answering, because "empty platform" and "stopped
backend" look identical otherwise.

## What the UI deliberately does

- **It shows the error the backend sent.** Code, message, per-field validation detail and the
  request id, so a report from a user can be matched to the backend's log lines for exactly
  that request.
- **A dash is not a zero.** Every metric the API reports as `null` — no observations, an
  unscorable question, no generator reached — renders as `—`. A rate that was never measured
  is never drawn as `0%`.
- **`insufficient_evidence` is a result, not an error.** It gets its own panel with the
  candidate count, what cleared the threshold and the fact that no generation stage ran.
- **Answers say what produced them.** An extractive answer states that the passages are
  verbatim and no model wrote the text; a generated one names the model. `answer_kind` is not
  decoration — it is the difference between quoting and generating.
- **No faithfulness or quality claim is displayed beyond what was measured.** The evaluation
  report says so where a reader would expect such a number.
- **Client-side validation is convenience only.** The server validates every payload again and
  its rejection is what is shown, including `INVALID_EVALUATION_DATASET`.

## Layout

```
src/
├── api/
│   ├── client.ts        # fetch + the error envelope, and ApiError
│   ├── endpoints.ts     # one typed function per endpoint
│   └── types.ts         # the backend contract, mirrored from the Pydantic schemas
├── components/          # Layout, states (loading/empty/error), ConfirmButton
├── features/
│   ├── knowledge-bases/ # list, detail, passages
│   ├── query/           # QueryPanel, TraceDetails
│   ├── evaluation/      # dataset parsing, run form, report
│   └── metrics/         # counters and latency
├── lib/                 # format (deterministic), useAsync
└── test/                # stubbed API, fixtures, setup
```

## Tests

54 tests, no network:

- the HTTP client: success, JSON and multipart bodies, `204`, the error envelope, a non-JSON
  error from a proxy, a transport failure, the caller's own abort, and per-field validation
  messages;
- formatting: milliseconds at three resolutions, `null` as a dash, bytes, UTC timestamps;
- dataset parsing: the valid case, defaults, and every rejection that would otherwise become a
  round trip;
- the query screen: answer, citations, trace, overrides sent as numbers, local rejection of an
  unusable `top-k`, and a server failure shown with its code and request id;
- knowledge bases: listing, creation (including `null` for a blank description), a conflict,
  the two-click delete, backing out of it, and a transport failure;
- a knowledge base: the empty state, the tab that fits the state, upload as multipart, a
  failed document with its reason and reprocess, indexed passages, a delete failure that keeps
  the row, and the ingestion polling that starts and then stops;
- the evaluation report: metrics, the `k` convention, a `null` rate as a dash, an absent
  generation stage, dataset problems and an unscorable question;
- the metrics screen: grouping, the latency columns, the empty snapshot and the error state;
- the bundled sample dataset being byte-identical to `evaluation/datasets/sample.json`.

Not covered, and stated rather than implied: there is **no browser-level or end-to-end test
suite**. The components are tested in jsdom against a stubbed API, and the dev-server proxy is
verified by hand (`curl http://127.0.0.1:5173/api/v1/metrics` while both processes run). A
Playwright suite is the obvious next step and is listed in
[ADR 0006](../docs/architecture/decisions/0006-frontend-architecture.md) as follow-up work.

## Not implemented

- **No authentication.** Every screen is open because every endpoint is open; sign-in arrives
  with Amazon Cognito in Phase 7.
- **No streaming answers.** The query endpoint answers in one response.
- **No saved history.** Questions and results live in the page, not on the server.
- **No cross-origin API access.** By design: the UI is served from the same origin as the API
  (proxied in development), so there is no CORS configuration and no credentialed
  cross-origin request.
- **No internationalisation, no theme toggle.** The UI is English and follows the operating
  system's colour scheme.
- **No code splitting.** One bundle; at 300 kB it is not worth the machinery yet.
- **No offline behaviour or optimistic writes.** Every write is confirmed by the server before
  the UI says anything succeeded.
