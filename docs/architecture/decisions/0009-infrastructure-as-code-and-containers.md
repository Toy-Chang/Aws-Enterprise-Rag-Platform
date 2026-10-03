# ADR 0009 — Infrastructure as code and containers

Status: accepted (Phase 7).

## Context

For the first six phases the repository could only be run as two local processes. That was
enough to review the retrieval pipeline and not enough to answer the question a deployment
asks: what runs, where, with which permissions, and what happens when a task dies? The
project's goal is a repository that is complete at the repository level, so the deployment
had to be described as code rather than as a paragraph of console instructions.

The honest constraint: this environment has no AWS credentials and no Docker daemon. A
plan, an apply, an image build and a `compose up` are therefore not things that can be
verified here, and the design had to be arranged so that the parts that *can* be verified —
configuration syntax, resource graph, formatting, and the resolved compose model — are
verified for real. "Written but never applied" is a state this repository states plainly
instead of dressing up.

Two further constraints: the API and the ingestion consumer must run the same code (a
document ingested by the queue has to be ingested exactly as the API would), and the local
stack has to stay usable with one command and no cloud account.

## Decisions

### 1. Terraform, split into modules that follow the resource graph

The root module wires nine modules — `network`, `storage`, `database`, `search`, `queue`,
`iam`, `auth`, `api`, `ingestion` — and passes values between them. The split is not
cosmetic:

- `iam` is separate because the search domain's access policy names the roles and the API's
  task definition needs the search endpoint. Roles in their own module turn what would be a
  cycle into two one-way references.
- Security groups live in `network`, including the rules that let the API and the consumer
  reach the database and the search domain. Those rules are *between* concerns, and this is
  the only place that knows both ends.
- `api` owns everything that serves (load balancer, cluster, both services, autoscaling),
  `ingestion` owns everything that consumes (function, event source mapping, its own image
  repository). One concern per module means one place to read for "what runs".

`local.name_prefix = "${project}-${environment}"` names every resource, so the same account
can hold a second stack, and `default_tags` carries `Project`, `Environment` and
`ManagedBy` without each resource repeating them.

### 2. Nothing in the configuration requires an AWS call to validate

Availability zones are derived from the region's letter suffix rather than from a
`aws_availability_zones` data source, and every reference between modules is an attribute
of a resource the same apply creates. The aws *provider* is still needed (that is what
`init -backend=false` downloads), but `terraform validate` evaluates the whole graph
offline, which is why it is a check that runs in this environment and in CI.

### 3. Images are built outside Terraform, and the consumer reuses the API image

Terraform does not build images; a `null_resource` wrapping `docker build` would hide a
build step inside an apply and still need a registry login. Instead the ECR repository
names are deterministic (`<name_prefix>-api`, `-frontend`, `-ingestion`), so the build and
push step can run before or after the first apply without depending on its output.

The ingestion function runs a second stage of the *same* Dockerfile:

```dockerfile
FROM runtime AS lambda
RUN pip install --no-cache-dir "awslambdaric>=2.0,<3.0"
ENTRYPOINT ["/usr/local/bin/python", "-m", "awslambdaric"]
CMD ["app.aws.handler.handler"]
```

One dependency set, one place where the code is installed, no possibility of the API and
the consumer disagreeing about a version. The image does not inherit from a Lambda base
image, so it installs the Runtime Interface Client itself; without that the invocation
never reaches the handler. The function's `image_config.command` names the same handler in
Terraform, so a push of the web image fails loudly instead of serving HTTP inside an
invocation.

### 4. The consumer reads its own database URL from Secrets Manager

An ECS task definition resolves `secrets.valueFrom` before the container starts, so the API
process simply sees `APP_DATABASE_URL`. A Lambda has no equivalent. The function is
therefore configured with `APP_DATABASE_SECRET_ARN` — an ARN is not a secret — and resolves
the URL through its role at cold start (`app/aws/secrets.py`). The password never appears
in a function configuration, which anyone with `lambda:GetFunctionConfiguration` can read,
and both processes end up with the identical assembled URL. A secret that cannot be read is
a `502 SECRET_UNAVAILABLE` and a failed invocation, which the error alarm reports, rather
than a process that starts against the wrong database.

### 5. Operational alarms are part of the stack, and their notification target is optional

Alarms exist for the API's 5xx rate, unhealthy hosts, DLQ depth, consumer errors and
throttles, and for the age of the oldest queued message. Their action is
`var.alarm_topic_arn`, which defaults to null: an alarm with no action is recorded and
notifies nobody, and that is stated in the variable's description rather than papered over
with a made-up topic. Creating an SNS topic and a subscription is deliberately left to the
operator, because an email address is not something infrastructure code should invent.

### 6. The container stack is a local stack, and the compose file says so

`docker-compose.yml` runs PostgreSQL, the API and the frontend, with OpenSearch behind an
`opensearch` profile. It is one command (`docker compose up -d`) with no cloud account, and
the backend runs as a single replica on purpose: the default vector store is in-process and
the polling worker is in-process, so a second replica would answer from an empty index and
two workers would race for the same document. Switching to the `opensearch` profile and a
queue is the documented scale-out path.

`docker compose config` resolves the model and was run; `docker compose build` and `up`
were not, because there is no Docker daemon in this environment, and `docker/README.md`
lists exactly that.

### 7. One origin, routed by path at the load balancer

The deployed stack serves the SPA and the API from one hostname: the load balancer sends
`/api/*` and `/health*` to the API target group and everything else to nginx. The browser
therefore calls a relative URL, and there is no CORS configuration to get wrong. In the
container stack the same property comes from nginx proxying to `backend:8000`; the deployed
nginx never sees an `/api` request, because the load balancer has already routed it.

### 8. What this phase does not contain

No remote state backend (a commented S3 example sits in `versions.tf`), no CI pipeline that
plans or applies, no DNS records, no certificate request, no migration tool, no image
signing, no container hardening beyond a non-root user, and no Kubernetes. Each is a real
piece of production infrastructure and none of them is required to make the deployment
readable and reproducible.

## Consequences

- The repository now answers "what runs where" without a console: nine modules, one root
  file, and a variable file whose every default is a decision with a comment.
- `terraform validate` and `fmt -check -recursive` pass, and `docker compose config`
  resolves with and without the OpenSearch profile. That is the verified part, and it is
  the part that catches the mistakes that are cheap to catch: a typo in a reference, a
  missing argument, a malformed policy, an unresolvable compose interpolation.
- Everything that needs an account is unverified: no plan, no apply, no resource, no image,
  no lambda invocation, no token from a live pool. A first deployment will find real
  problems, and this document is where that is admitted rather than hidden.
- The first apply cannot create the ECS services or the function before their images exist.
  The deployment procedure in `docs/deployment/terraform.md` is staged for that reason, and
  the naming convention is what makes the staging orderly.
- Cost is concentrated in three places (the search domain, the database, and the NAT
  gateway), and the variables that govern them default to a production shape. A trial run
  has to turn them down explicitly, which is the correct order of defaults for a stack that
  is meant to be deployed by someone who has not read all of it.

## Alternatives considered

- **One flat `main.tf`.** Fewer files, and the IAM/search relationship would have to be
  expressed as a cycle or as a single enormous resource group. Modules make the two
  dependency directions explicit.
- **CDK or Pulumi.** Both are code, and both add a language runtime and a toolchain to a
  repository that currently needs Python, Node and Terraform. Terraform's plan is also the
  artifact a reviewer reads.
- **SAM or the Serverless Framework for the consumer.** Would introduce a second packaging
  mechanism for one function, and would not cover the ECS side at all.
- **Running the consumer as an ECS service with a long poll.** Perfectly workable, and it
  loses the per-message retry semantics: the SQS event source mapping with
  `ReportBatchItemFailures` deletes exactly the messages that were processed, which is the
  property the consumer's contract depends on.
- **A data source per availability zone.** More "correct" in the abstract and it makes the
  configuration depend on an AWS call, which would remove the offline validation.
- **Committing a remote state backend.** A shared backend needs an account, a bucket and a
  locking table; committing a guess at those names would be worse than the commented
  example.
- **Documenting the deployment as console steps.** Not reproducible, not reviewable, and
  not testable at all — not even the parts that could be tested here.

## Follow-up work

- A remote state backend with locking, and a CI job that runs `fmt -check`, `validate` and
  `plan` against a real account with a read-only role.
- An SNS topic and subscription, so the alarms that already exist reach a person.
- Container hardening: read-only root filesystem, dropped capabilities, resource limits,
  and a non-root nginx.
- A migration tool (Alembic) before the schema changes for the first time; the current
  startup `create_all` cannot express a column change.
- A second ECS service for the consumer if throughput ever justifies it, and `pgvector` as
  an alternative to a separate search domain for smaller deployments.
