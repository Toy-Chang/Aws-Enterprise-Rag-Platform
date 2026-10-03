# Frontend image: a Node stage builds the SPA, an nginx stage serves it and proxies the
# API for it.
#
# The compose service uses this repository root as its build context, not frontend/,
# because the runtime stage needs docker/nginx.conf next to the sources. Both stages copy
# explicit paths, so nothing else from the context enters the image.
#
# Build it with compose (see docker/README.md). Building it by hand means running from the
# repository root:
#   docker build -f frontend/Dockerfile -t rag-frontend .

# --- build stage ---------------------------------------------------------------
FROM node:22.11-alpine AS build

# pnpm is pinned to the version that produced frontend/pnpm-lock.yaml, because
# `--frozen-lockfile` refuses to proceed against a lockfile another major version wrote.
# Corepack is deliberately not used: it would resolve the version from the environment
# rather than from this line, and package.json declares no packageManager field.
RUN npm install --global --no-fund --no-audit pnpm@12.8.1

WORKDIR /build

# The manifest and the lockfile first: this layer is the expensive one and it only has to
# run again when a dependency changes.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Configuration and sources. vite.config.ts is copied because the build reads it.
COPY frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/public ./public
COPY frontend/src ./src

# The UI calls same-origin paths (/api/v1/...) by default, and in this image nginx serves
# both the SPA and the API from one origin, so the default is an empty base URL. Set the
# build arg only to point the built assets at a different origin; it must have no trailing
# slash (the client concatenates paths onto it).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# `pnpm build`, i.e. `vite build`, which does not typecheck. The suite that does
# (`pnpm typecheck && pnpm test`) belongs to CI, where a failure is a red build rather
# than an image that cannot be produced.
RUN pnpm run build

# --- runtime stage -------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# The proxy configuration lives in the repository, not inline here, so the SPA fallback,
# the cache policy and the upstream can be reviewed and changed without touching the
# Dockerfile. nginx reads every *.conf in this directory.
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

# nginx:alpine starts as root by default. Running as the image's own nginx user is enough
# for a static server and a reverse proxy, but it can no longer create its pid file or its
# temporary buffer directories, so those are created and chowned here. Port 80 stays: the
# container's capability set includes NET_BIND_SERVICE and Docker lowers
# net.ipv4.ip_unprivileged_port_start to 0, so an unprivileged process may bind it.
RUN touch /var/run/nginx.pid \
 && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /etc/nginx/conf.d
USER nginx

EXPOSE 80

# /healthz is answered by this nginx itself, so the probe reports on the web server rather
# than on the API behind it: a backend outage must not look like a broken frontend
# container, and compose gates the stack on the backend's own readiness check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
