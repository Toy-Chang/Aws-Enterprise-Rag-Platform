# ADR 0006 — Frontend architecture

- **Status:** accepted
- **Phase:** 6
- **Date:** 2026-01-01

## Context

The backend exposes four things worth looking at: knowledge bases and their indexed passages,
a query endpoint that answers with citations and a per-stage trace, a metrics snapshot, and an
evaluation endpoint that measures the pipeline against labelled data. Until this phase all of
them were reachable only with `curl`, and the two most informative — the trace and the
evaluation report — were effectively invisible.

Two properties of the backend shape every decision here. It has exactly one error envelope
(`request_id` plus `code`, `message`, `details`), and it reports "not measured" as `null`
rather than as zero. A UI that flattens either of them throws away the information the backend
went to trouble to produce.

## Decisions

### 1. Same-origin requests and a dev proxy, not CORS

The UI calls `/api/v1/...` on its own origin. In development Vite proxies those paths to
`127.0.0.1:8000`; in a deployment a reverse proxy serves the static build and the API from one
origin. The browser therefore never makes a cross-origin request.

This is not just convenience. Cross-origin access would have meant adding CORS middleware to
the backend with an allowed-origin list, and the moment credentials are involved (cookies for
Cognito in Phase 7) it also means CSRF protection and `SameSite` decisions. None of that is
needed for the shape the platform actually has, and adding it now would be security
configuration written before there is anything to secure. The trigger to revisit is
authentication in Phase 7: if the UI and API end up on different origins, CORS becomes a real
decision with a real threat model, and this ADR is where that argument goes.

### 2. The contract is hand-written TypeScript, not generated

`src/api/types.ts` mirrors `backend/app/schemas/*.py` field for field, including which fields
are nullable. There is no OpenAPI codegen step.

A generated client is a legitimate choice, and this one has a real cost: when a schema changes,
the compiler points at the file that must be edited, and someone has to edit it. The reason to
prefer that here is what happens when nobody does. A generated client that is not regenerated
keeps compiling against the old shape and fails at run time, in the browser, with `undefined`
where a number was expected. A hand-written file that disagrees with the backend fails at
`pnpm typecheck`, before anything ships. For a contract of this size — six response types, four
request types — the manual step is cheaper than the silent drift. If the surface grows past
what one person can hold, codegen with a CI check that the generated file is current is the
better answer.

### 3. One client that keeps the whole error

`src/api/client.ts` is the only place that calls `fetch`. It turns a failed response into an
`ApiError` carrying `status`, `code`, `message`, `details` and `requestId`, and distinguishes
three failures that are genuinely different:

- the backend rejected the request and said why (the envelope);
- something that is not the application answered — a proxy's HTML page, a truncated response —
  which is reported as `UNEXPECTED_RESPONSE` rather than crashing on `JSON.parse`;
- the request never completed, reported as `NETWORK_ERROR` with the underlying reason.

Every screen renders that, and the request id is shown because it is what makes a user's report
findable in the backend's logs. A generic "something went wrong" would discard the one field
that turns a bug report into a log query.

The client also re-throws the caller's own `AbortError` untouched instead of dressing it as a
failure: an aborted request is the application's own doing, and reporting it as an error state
would make a screen flash an error every time its inputs change.

### 4. No data-fetching library and no global store

There are five read endpoints, no cache to invalidate across screens, no optimistic writes and
no shared client state beyond the URL. A query library would be more machinery than the problem
has, and a state container would have one consumer.

`src/lib/useAsync.ts` is the whole data layer: it aborts the in-flight request when the inputs
change, ignores a response that arrives after a newer one started, and offers a stable
`reload`. Those three behaviours are exactly what a hand-rolled `useEffect` usually gets wrong,
and they are the reason for the hook to exist at all. The trigger to revisit is real shared
state or a cache with invalidation — neither exists yet.

### 5. `null` is rendered as "not measured", never as zero

The backend reports a rate with no denominator as `null`, an unscorable question's metrics as
`null`, and an absent generation stage as `null`. The UI renders all of them as `—`, and
formats dates and numbers deterministically (explicit `en-US`, UTC timestamps in the shape the
logs use) so a screenshot, a log line and a test agree.

A dashboard that drew 0% for "no observations" would be actively misleading about the
abstention behaviour this platform is built around, and would do it in the direction that looks
like a failure when it is actually an absence of evidence.

### 6. The trace and the citations are the product, not a debug panel

The answer comes first, and the trace sits behind a `<details>` directly beneath it: candidate
counts, what cleared the threshold, what the context budget dropped, whether a reranker ran,
the model name, the durations and the request id. The evaluation report carries the same
principle — the *policies* the run used (`k`, `min_score`) are printed with the numbers,
because a metric produced under a different retrieval policy cannot be read without them.

`insufficient_evidence` is rendered as a result with the counts that explain it, not as an
error. It is the platform declining to answer, which is the behaviour the whole design exists
to produce, and colouring it red would train an operator to read it as a malfunction.

### 7. The evaluation screen bundles a copy of the committed dataset, and a test guards it

The dataset lives in the repository at `evaluation/datasets/sample.json`, which the browser
cannot read. Rather than have the operator paste JSON before the screen does anything, the
build ships a copy at `public/sample-datasets/platform-runbooks-smoke.json` and loads it on
mount. A copy can drift, so `src/sample-dataset.test.ts` asserts the bundled file is
byte-identical to the committed one and that it satisfies the dataset's own rules.

Duplicating data is a cost; the alternative was a backend endpoint that serves datasets by name,
which is a file-serving surface this phase does not need. The test is what makes the
duplication safe, and it is the reason the copy is acceptable.

### 8. Polling only where the backend genuinely defers work

Ingestion is asynchronous: an upload returns `pending` and a worker parses, chunks and embeds
the document. The document list therefore refreshes itself every 1.5 s **while something is
pending or processing**, and stops as soon as nothing is. Everywhere else a screen loads once
and has a manual refresh.

Polling that never stops is how a UI turns into a load generator, and polling that does not
exist at all makes ingestion look broken. Both are avoided by tying the timer to the state that
actually means "work in progress".

### 9. Plain CSS with custom properties, no framework

The UI is tables, forms and result panels. A utility framework would add a build step, a
dependency and a class-name vocabulary for a few hundred lines of CSS. Colours are variables so
the dark scheme is one block, and the layout collapses to one column on a narrow screen.
Revisit if the UI grows componentry that genuinely benefits from a design system.

### 10. Client-side validation is convenience, and says so

The query form and the evaluation form check the obvious things locally — a blank question, a
non-numeric or out-of-range `top-k`, a dataset that is not JSON — so the user is not sent on a
round trip to be told. None of it is trusted: the backend validates every payload again, and
the backend's rejection is what is displayed. The dataset rules that make the metrics
meaningful (a label naming a document that is not in the corpus, an answerable question with no
label) are checked on the server only, because they are semantic rather than syntactic.

## Alternatives considered

- **CORS middleware on the backend.** Rejected; see decision 1. Not needed for same-origin, and
  it would have to be revisited with authentication anyway.
- **OpenAPI code generation.** Deferred with the reasoning in decision 2.
- **TanStack Query or SWR.** Rejected for now; five reads with no shared cache.
- **A global store (Redux, Zustand, Context).** Rejected; there is no shared state.
- **Server-side rendering or a meta-framework.** Rejected: this is an authenticated operator
  tool, and there is no SEO or first-paint problem to solve.
- **A component library.** Rejected; the surface is small and a library would be the largest
  dependency in the project.
- **A Playwright end-to-end suite.** Not written in this phase. It is the right way to cover
  the browser-level behaviour — the dev proxy, real fetch, real rendering — and it needs a
  browser download and two running processes in CI. The component suite plus a documented
  manual proxy check is what exists, and this is stated in the README rather than implied away.
- **A backend endpoint that serves named datasets.** Rejected for this phase; see decision 7.
- **Streaming answers.** The backend has no streaming endpoint; the UI does not pretend to have
  one.
- **Optimistic writes.** Rejected: every write here is confirmed by the server, and showing an
  upload as complete before ingestion has even been queued would be a lie the status column
  then contradicts.

## Consequences

- The UI cannot be pointed at a backend on another origin without either a proxy or CORS work.
  That is a deliberate constraint, and it is the shape a deployment has anyway.
- Nothing about the frontend is tested in a real browser. The dev proxy is the one piece of
  wiring the component tests cannot reach.
- The backend's error envelope and its `null` conventions are now load-bearing for the UI. A
  change to either is a frontend change, which is the intended coupling: the contract is the
  interface between them.

## Follow-up work

- Phase 7: authentication (Cognito), which decides whether CORS and credentialed requests
  become real decisions; and serving the built UI from the same origin as the API in the
  docker-compose and Terraform stacks.
- A Playwright suite for the browser-level behaviour, including the proxy and a real ingestion
  round trip.
- Code splitting if the bundle grows past a few hundred kilobytes, and a component library if
  the surface grows past what hand-written CSS can hold.
- Streaming answers if the query endpoint ever supports them.
