# Docker stack

Runs the whole platform locally in containers: PostgreSQL, the API
(`python -m app`) and the built SPA behind nginx. `docker-compose.yml` is at the
repository root; this directory holds the nginx configuration the frontend image copies
and this document.

Files:

| Path | Role |
| --- | --- |
| `docker-compose.yml` | The stack: services, profiles, volumes, interpolated settings |
| `backend/Dockerfile`, `backend/.dockerignore` | API image (context: `backend/`) |
| `frontend/Dockerfile`, `frontend/.dockerignore` | SPA image: Node build stage + nginx runtime stage |
| `docker/nginx.conf` | Copied to `/etc/nginx/conf.d/default.conf` in the frontend image |
| `.env.docker.example` | Template for the values `docker compose` interpolates |

## Start

```bash
docker compose up -d --build      # build both images and start postgres, backend, frontend
docker compose ps                 # wait for healthy on all three
```

Nothing has to be configured first: every value in `docker-compose.yml` falls back to a
local default, and no `.env` file is required. To change a value:

```bash
cp .env.docker.example .env       # then edit; compose reads it automatically
```

Validation that needs no daemon (this is what a review or CI can run):

```bash
docker compose config                        # the fully resolved configuration
docker compose --profile opensearch config   # the same, with the optional service
```

`docker compose config` fails on a misspelled service reference, an undefined volume, an
invalid interpolation or a malformed healthcheck, so it is a real check rather than a
formality.

## URLs

| URL | What it is |
| --- | --- |
| http://127.0.0.1:8080 | Operator UI (nginx serves the SPA) |
| http://127.0.0.1:8080/api/v1/... | The API through the same origin (nginx proxies `/api/`) |
| http://127.0.0.1:8080/health, `/health/ready` | The backend's probes through the proxy |
| http://127.0.0.1:8080/healthz | nginx's own liveness probe (not proxied) |
| http://127.0.0.1:8000/docs | OpenAPI page, straight to the API container |
| http://127.0.0.1:8000/api/v1/metrics | Counters and latency summaries |

The two host ports come from `FRONTEND_PORT` (8080) and `BACKEND_PORT` (8000). The
database has no published port; see the commented block in the `postgres` service if you
want one.

## How the frontend reaches the API

The built UI calls relative paths (`/api/v1/...`, from `frontend/src/api/client.ts`), so
the browser only ever talks to the origin it loaded the page from. `docker/nginx.conf`
forwards `/api/`, `/health` and `/health/ready` to `http://backend:8000` — `backend` is
the compose service name and 8000 is the port the API listens on in its container — and
serves everything else from `dist/`, falling back to `index.html` so client-side routes
such as `/knowledge-bases/{id}` survive a reload.

The equivalent in development is `frontend/vite.config.ts`, which proxies the same two
paths to `127.0.0.1:8000`. Nothing in the application needs CORS, and the backend
therefore has no CORS configuration.

`X-Request-ID` is forwarded unchanged; when a caller does not send one, nginx mints an
identifier of the same shape, and the backend reuses whatever arrives. That is what makes
a request id in the UI's error envelope findable in both logs.

`VITE_API_BASE_URL` is available as a build arg (`docker compose build --build-arg`, or the
`args:` block in `docker-compose.yml`) for the case where the assets must point at another
origin. Leaving it empty is the supported default: an external API origin is a
cross-origin request that the backend is not configured to answer.

## Profiles

`docker compose up -d` starts `postgres`, `backend` and `frontend` only.

| Profile | Service | What it is for |
| --- | --- | --- |
| `opensearch` | `opensearch` | A single-node OpenSearch to exercise the k-NN adapter locally |

```bash
# memory (default): the in-process exact index, no extra service
docker compose up -d

# OpenSearch: one variable switches the vector store, then start the profile
echo 'APP_VECTOR_STORE_BACKEND=opensearch' >> .env
docker compose --profile opensearch up -d
```

Which settings go with the profile: `APP_VECTOR_STORE_BACKEND=opensearch` plus the
`APP_OPENSEARCH_*` values that are already set in `docker-compose.yml`
(`APP_OPENSEARCH_ENDPOINT=http://opensearch:9200`, the index name, and the placeholder
basic-auth pair). The endpoint is inert while the backend is `memory`; the reverse — an
endpoint without `opensearch` — is also harmless, while `opensearch` without an endpoint
is refused when the process starts. A local single node disables the security plugin, so
the placeholder credentials are sent and ignored; a real cluster needs real ones.

The vector store and the embeddings have to agree on the width
(`APP_EMBEDDING_DIMENSIONS`), and switching stores does not migrate vectors: re-ingest, or
drop the data (below). This node has no TLS, no authentication and no backups — it is for
local verification, not a deployment.

## Logs

```bash
docker compose logs -f backend        # one service
docker compose logs -f                # everything, interleaved
docker compose logs --tail=100 backend
```

The backend logs are structured JSON (`APP_LOG_FORMAT=json`) because that is what a log
pipeline expects; set `APP_LOG_FORMAT=console` in `.env` for a readable terminal. Every
request record carries the request id, so a UI error can be located with:

```bash
docker compose logs backend | grep <request-id>
```

nginx writes its access log to the container's stdout, so `docker compose logs frontend`
shows the requests that reached the proxy.

## Resetting data

Named volumes hold everything that has to survive a rebuild:

| Volume | Holds |
| --- | --- |
| `aws-enterprise-rag-platform_postgres_data` | Knowledge bases, documents and passages |
| `aws-enterprise-rag-platform_documents` | Uploaded files (`APP_STORAGE_DIR=/data/documents`) |
| `aws-enterprise-rag-platform_opensearch_data` | The optional node's index |

```bash
docker compose down                 # stop, keep the data
docker compose down -v              # stop and delete every volume (a clean platform)
docker compose rm -sf opensearch    # remove the profile's container only
```

There are no migrations: the schema is created at startup from the models
(`init_db`), so a database that predates a model change has to be recreated with
`down -v` rather than upgraded in place. `docker compose down -v` is also what a rebuild
after changing `APP_EMBEDDING_DIMENSIONS` or the vector store needs, because stored vectors
are not converted.

## Local-only settings

Everything below is what makes the stack usable on one machine and is not appropriate as
it stands:

| Setting | Compose value | What a deployment must do |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `rag` via `${POSTGRES_PASSWORD:-rag}` | Replace it, and do not reuse this file |
| `APP_ENVIRONMENT` | `local` | Set the real environment. `production` is *refused* by the application while authentication is off (`APP_AUTH_BACKEND=none`), which is deliberate: an open API in production is not something to warn about |
| `APP_STORAGE_BACKEND=local` | Files in a volume | Documents do not survive the loss of that volume; move to S3 |
| `APP_EMBEDDING_PROVIDER=local` | Lexical hashing model | Metrics in the root README describe this model only |
| `APP_GENERATION_PROVIDER=local` | Extractive answers (quoted passages) | Answers are quotations, not generation |
| `APP_VECTOR_STORE_BACKEND=memory` | In-process index, rebuilt at startup | Also the reason there is exactly one backend replica: a second one would hold its own index. Scale out with the `opensearch` profile and a queue |
| `APP_QUEUE_BACKEND=none`, worker on | The worker polls the database | With more than one replica, or with a queue, turn the worker off — two consumers would ingest the same document twice |
| `opensearch` profile | Single node, no TLS, no auth | Do not expose it; use a managed domain |
| No published database port | Reachable on the compose network only | — |
| Backend published on 8000 | For curl and `/docs` | Front it with the real entry point only |

Two structural notes for a real deployment: the images run as non-root
(`appuser`, `nginx`), but nothing here is a hardening baseline (no read-only root
filesystem, no dropped capabilities, no resource limits), and the backend still needs
`psycopg` — see the note below.

## Two known deviations from the repository layout

1. **`psycopg` is installed by the Dockerfile, not declared in `pyproject.toml`.**
   `backend/pyproject.toml` has no PostgreSQL driver in any extra, and this stack points
   `APP_DATABASE_URL` at `postgresql+psycopg://`. The image installs
   `psycopg[binary]>=3.2,<4.0` in its dependency layer, next to `.[aws,auth]`. Adding a
   `postgres` extra to `pyproject.toml` would be the clean fix; this file was left
   untouched because it is outside the scope of the container work.
2. **The frontend build context is the repository root**, not `frontend/`, because the
   runtime stage copies `docker/nginx.conf` as well as the sources. The Dockerfile copies
   explicit paths, so `node_modules/` and `dist/` never enter the image — but they are
   still *sent* to the daemon, because a `.dockerignore` at the context root (which would
   be the right place) is not part of this change. `frontend/.dockerignore` applies to a
   `docker build frontend/` invocation. Adding a root `.dockerignore` with `node_modules/`,
   `frontend/node_modules/`, `frontend/dist/`, `backend/.venv/` and `.git/` would cut the
   transfer; it changes nothing about the resulting image.

The `auth` extra referenced in `backend/Dockerfile` (`pip install ".[aws,auth]"`) installs
`pyjwt[crypto]`, which is what token verification needs. pip only warns about an extra that
is not declared (`does not provide the extra 'auth'`), so that line kept working while the
extra was being added and needs no change now that it exists.

Compose deliberately does not forward the `APP_AUTH_*` / `APP_COGNITO_*` family: only the
variables listed under a service's `environment:` reach the container, so a half-wired
identity provider would be a switch that cannot be completed from `.env`. Authentication is
configured by editing the service (or by deploying the image somewhere that injects the
whole environment), and `APP_ENVIRONMENT=local` is what keeps the permissive default legal.

## Validation status

Static validation, run without the Docker daemon (it is not running on this machine):

| Check | Result |
| --- | --- |
| `docker compose config` | exit 0, fully resolved configuration printed |
| `docker compose --profile opensearch config` | exit 0, the profile adds the fourth service and its volume |
| `docker compose --env-file .env.docker.example config` | exit 0, byte-identical to the config above (the template restates the defaults) |
| Every `APP_*` name in `docker-compose.yml` exists in `backend/.env.example` | pass: 19 names, checked one by one against the resolved compose model |
| nginx upstream matches the compose service name and the container port | pass (`http://backend:8000` in `docker/nginx.conf`; service `backend`; `APP_PORT=8000`, `EXPOSE 8000`, published `8000:8000`) |
| The nginx config the frontend image copies exists at that path | pass (`COPY docker/nginx.conf` → `docker/nginx.conf`, and to `/etc/nginx/conf.d/default.conf`) |
| Every `COPY` source in both Dockerfiles resolves in its build context | pass, against the paths on disk |
| `docker/nginx.conf` parses as a complete nginx configuration | pass: `crossplane` parsed it inside a generated `http` block, status ok, no errors, and every directive in a valid context (syntax and context, not `nginx -t`) |
| Pinned image tags exist in their registries | pass: Docker Hub answers 200 for python 3.12-slim, postgres 16.4-alpine, nginx 1.27-alpine, node 22.11-alpine, opensearch 2.19.1 |
| The image needs no compiler for its compiled dependencies | pass: `pydantic-core`, `uvloop`, `httptools`, `watchfiles`, `psycopg-binary`, `cryptography` and `sqlalchemy` publish cp312 manylinux wheels for aarch64 and x86_64 |
| pip tolerates the not-yet-declared `auth` extra | pass: reproduced with a stub project, exit 0 with `does not provide the extra 'auth'` |

Not validated here, because it needs the daemon and a running stack:

| Check | Status |
| --- | --- |
| `docker compose build` (both images) | NOT RUN |
| `docker compose up -d` and healthy services | NOT RUN |
| `nginx -t` on `docker/nginx.conf` | NOT RUN (nginx is not installed on this machine) |
| Upload → ingest → `ready` through the container stack | NOT RUN |
| Query with citation through the container stack | NOT RUN |
| OpenSearch profile against a running node | NOT RUN |

The commands that validate those, in order:

```bash
# 1. Build both images
docker compose build

# 2. Start and wait for health
docker compose up -d
docker compose ps                    # postgres, backend, frontend must be healthy

# 3. Probes through the proxy (the same path the UI uses)
curl -s http://127.0.0.1:8080/health/ready
curl -s http://127.0.0.1:8080/api/v1/metrics

# 4. Create a knowledge base and upload a document
KB_ID=$(curl -s -X POST http://127.0.0.1:8080/api/v1/knowledge-bases \
  -H 'Content-Type: application/json' \
  -d '{"name": "platform-runbooks", "description": "Container smoke test"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')

DOC_ID=$(curl -s -X POST "http://127.0.0.1:8080/api/v1/knowledge-bases/$KB_ID/documents" \
  -F "file=@docs/deployment/aws.md" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')

# 5. Wait for the worker to finish, then ask a question
curl -s "http://127.0.0.1:8080/api/v1/knowledge-bases/$KB_ID/documents/$DOC_ID"   # status: ready
curl -s -X POST "http://127.0.0.1:8080/api/v1/knowledge-bases/$KB_ID/query" \
  -H 'Content-Type: application/json' \
  -d '{"question": "How often do database credentials rotate?"}'
```

If a container does not become healthy, `docker compose logs <service>` is the first
place to look: a backend that exits immediately usually names an unusable setting (for
example `opensearch` without an endpoint, or a mistyped database URL), and one that stays
`starting` while the database is unreachable names the database.
