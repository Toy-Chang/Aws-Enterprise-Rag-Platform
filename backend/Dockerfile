# API service image. The stack that runs it is docker-compose.yml at the repository
# root; what each profile runs and which settings are local-only is in docker/README.md.
FROM python:3.12-slim AS runtime

# Unbuffered output because in a container stdout is the only place logs can go, and no
# .pyc files because they would only be written to a filesystem that is discarded with the
# container. APP_HOST/APP_PORT are container defaults: the process has to listen on every
# interface to be reachable from another container, and 8000 is what EXPOSE and the
# healthcheck below use.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

WORKDIR /srv/app

# Dependencies first, and from a stub of the package rather than from the real source:
# this layer then survives every change to a route, a service or a model, so an edit
# costs seconds instead of a full reinstall. The stub exists only because setuptools needs
# a package to build; it is removed in the same layer.
#
# `auth` (pyjwt with cryptography) is requested as well because the deployment image must
# be able to verify Cognito tokens. It is an extra, and pip only warns when an extra is not
# declared (`WARNING: ... does not provide the extra 'auth'`), so this line also worked
# before the extra landed and needed no second edit. Verified locally against a stub
# project: exit code 0 with the warning.
#
# `postgres` is what points APP_DATABASE_URL at postgresql+psycopg://; the binary wheel
# bundles libpq, so the image needs neither a compiler nor PostgreSQL client libraries.
COPY pyproject.toml ./
RUN mkdir -p app \
 && touch app/__init__.py \
 && pip install ".[aws,auth,postgres]" \
 && rm -rf app build ./*.egg-info

# The application itself. Installed with --no-deps as well, so site-packages holds the
# real package (not the stub above) and `python -m app` works from any directory, not only
# from the workdir that happens to contain the sources.
COPY app ./app
RUN pip install --no-deps . \
 && rm -rf build ./*.egg-info

# An unprivileged user for the process, and a data directory it owns. Docker seeds a new
# named volume from the image, so chowning /data here is what makes APP_STORAGE_DIR
# writable in the container without a root entrypoint repairing permissions at start.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data/documents \
 && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000

# Liveness only: /health answers as soon as the process serves requests, so a temporarily
# unreachable database does not restart a container that is working. Readiness -- the
# check that also probes the database -- is what compose waits for before it starts
# dependents, and is asserted there rather than duplicated here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "app"]

# The ingestion Lambda runs the same code and the same dependencies, so it is built from
# this image with one added layer rather than from a second Dockerfile that would drift.
#
#   docker build --target lambda -t <ingestion-repository>:<tag> backend
#
# `awslambdaric` is the Runtime Interface Client: an image that does not inherit from a
# Lambda base image has to install it and make it the entrypoint, or the invocation never
# reaches the handler. The CMD names the handler inside app/aws/handler.py, overriding the
# web server this image starts by default; Terraform sets the same value in the function's
# image configuration, so the deployed handler is stated in two places that are visible
# from each other.
#
# The function's own image configuration wins over CMD, so a push of the wrong tag (the web
# image) still fails loudly rather than serving HTTP inside a Lambda invocation.
FROM runtime AS lambda

USER root
RUN pip install --no-cache-dir "awslambdaric>=2.0,<3.0"

ENTRYPOINT ["/usr/local/bin/python", "-m", "awslambdaric"]
CMD ["app.aws.handler.handler"]
