# The Terraform stack

This document describes what the configuration under `infrastructure/terraform/` creates
and in what order a human has to drive it. It is written from the code in this repository.

> **Nothing here has ever been applied.** `terraform plan` and `terraform apply` have not
> been run: there are no AWS credentials in this environment and no account to point at.
> No resource in this stack has ever existed. What *is* verified is listed at the end, and
> it is verification by `terraform init`, `validate` and `fmt`, not by deployment. Expect
> to fix details only a real apply can reveal — an IAM action, a service quota, an
> instance class that the chosen region does not offer.

## What the root module creates

`main.tf` wires nine modules in dependency order; `name_prefix` is
`<project>-<environment>` everywhere, so one account can hold the stack more than once by
changing `environment` alone.

| Module | Creates | Why it exists |
| --- | --- | --- |
| `network` | VPC, internet gateway, a public and a private subnet in each of two zones, NAT gateway(s), route tables, and five security groups | Gives the tasks private addresses and puts the rules *between* concerns — who may reach the database, who may reach the search domain — in one file |
| `storage` | The document S3 bucket with public access blocked, versioning, SSE-KMS (`aws/s3`), a TLS-only bucket policy and a lifecycle rule | The uploaded bytes live here; the bucket is not created by the application |
| `database` | RDS PostgreSQL (gp3, encrypted, `publicly_accessible = false`), its subnet group, and a Secrets Manager secret holding the assembled URL | The source of truth for knowledge bases, documents, chunks and evaluation runs |
| `queue` | The ingestion SQS queue, its dead-letter queue, redrive policy, SSE-SQS, long polling, and the DLQ-not-empty alarm | Ingestion is asynchronous so several tasks can serve requests while one consumer drains the queue |
| `iam` | Three roles and their policies: the API task role, the ECS execution role and the ingestion role | Each process gets only the calls it makes: the API publishes but never consumes, the consumer consumes but never deletes documents |
| `search` | The OpenSearch domain (encrypted at rest and node to node, HTTPS enforced, IAM access policy) plus its log group and log resource policy | Holds the chunk text and the k-NN vectors; the index itself is created by the application on first write |
| `auth` | Cognito user pool, a public app client, the hosted UI domain and the `viewer`/`editor`/`admin` groups | Identity for a deployment, where the local stack has none; details are in `docs/deployment/cognito.md` |
| `api` | Two ECR repositories, the ECS cluster, the ALB and both listeners, two target groups, two task definitions, two services, autoscaling and four alarms | The serving path: one origin, with `/api/*` and `/health*` routed to the API and everything else to the frontend |
| `ingestion` | The ingestion ECR repository, the Lambda function, its event source mapping, a log group and three alarms | Consumes the queue with `ReportBatchItemFailures` so a partially failed batch is retried |

The root also creates nothing itself. Outputs are in `outputs.tf`; every value a caller
needs to reach the stack is there.

## Prerequisites

| Requirement | Why |
| --- | --- |
| Terraform `>= 1.6.0` | `versions.tf` requires it; the AWS provider is pinned to `~> 5.60` and `init` writes the exact version into `.terraform.lock.hcl` |
| AWS credentials | Everything here is a real AWS resource. The deploying identity needs write access to VPC, EC2, RDS, S3, SQS, ECR, ECS, ELB, Lambda, CloudWatch, IAM, Secrets Manager, OpenSearch and Cognito — creating IAM roles and attaching policies included, which is why a broad deployment role is the practical answer |
| A `db_password` | Required, no default, and at least 16 characters because RDS refuses a shorter master password. Pass it as `TF_VAR_db_password` or in a `terraform.tfvars` that is never committed |
| A region that offers the instance classes | `eu-west-1` is the default. `search_instance_type` has to be a k-NN capable family |

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars     # then edit; git-ignores it
export TF_VAR_db_password='...'                 # or put it in the tfvars file
terraform init
```

Remote state is deliberately not configured. `versions.tf` holds a commented `backend
"s3"` block: a committed backend block would make `terraform init` fail for anyone without
that bucket, so whoever has one uncomments it or passes `-backend-config`.

## The staged deployment this stack needs

Images are built and pushed outside Terraform, and a task definition or Lambda function is
created with an image URI that has to exist. The first apply on a fresh account therefore
cannot be the whole stack: the ECR repositories have to exist before anything can be
pushed, and the compute can only be created once something has been.

| Step | Command | Result |
| --- | --- | --- |
| (a) Initialise | `terraform init` | Providers downloaded, lock file written, modules registered |
| (b) First apply | `terraform apply -target=module.api.aws_ecr_repository.api -target=module.api.aws_ecr_repository.frontend -target=module.ingestion.aws_ecr_repository.ingestion` | The three repositories, and nothing else |
| (c) Build and push | the three `docker build` / `docker push` commands below | One image in each repository |
| (d) Full apply | `terraform apply` | Everything, with the images already in place |
| (e) Read the outputs | `terraform output` | The addresses and identifiers in `outputs.tf` |

The repository names are deterministic, which is what makes (b) possible and (c)
scriptable without reading outputs first. They are `<project>-<environment>-api`,
`<project>-<environment>-frontend` and `<project>-<environment>-ingestion`
(`aws_ecr_repository.api`, `.frontend` and `aws_ecr_repository.ingestion`), so with the
defaults they are `rag-platform-production-api` and so on. Each repository has a lifecycle
policy that expires everything but the ten most recent images, and `scan_on_push` is on.

```bash
# (c) The API and frontend images. The build context is the repository root for the
# frontend because its runtime stage also copies docker/nginx.conf.
aws ecr get-login-password --region eu-west-1 \
  | docker login --username AWS --password-stdin <account-id>.dkr.ecr.eu-west-1.amazonaws.com

docker build --platform linux/amd64 -t <account-id>.dkr.ecr.eu-west-1.amazonaws.com/rag-platform-production-api:latest backend
docker push <account-id>.dkr.ecr.eu-west-1.amazonaws.com/rag-platform-production-api:latest

docker build --platform linux/amd64 -f frontend/Dockerfile \
  -t <account-id>.dkr.ecr.eu-west-1.amazonaws.com/rag-platform-production-frontend:latest .
docker push <account-id>.dkr.ecr.eu-west-1.amazonaws.com/rag-platform-production-frontend:latest

# The ingestion image is the API image with the Lambda runtime layer, built from the same
# Dockerfile. `--target lambda` installs awslambdaric and makes the handler the entrypoint.
docker build --platform linux/amd64 --target lambda \
  -t <account-id>.dkr.ecr.eu-west-1.amazonaws.com/rag-platform-production-ingestion:latest backend
docker push <account-id>.dkr.ecr.eu-west-1.amazonaws.com/rag-platform-production-ingestion:latest
```

`<account-id>` is a placeholder: it is whatever `aws sts get-caller-identity` answers for
the account being deployed into, and it is not known here.

Two consequences of `--platform linux/amd64`:

- it has to match `cpu_architecture`, which defaults to `X86_64`. An Apple silicon machine
  builds arm64 unless told otherwise, and a task whose image architecture and
  `runtime_platform` disagree never starts. Either pass `--platform linux/amd64` as above,
  or set `cpu_architecture = "ARM64"` and build natively.
- the ingestion module lower-cases the value for Lambda (`x86_64`), because the two
  services spell the same architecture differently.

If the three default tags are not what should run, set `api_image_tag`,
`frontend_image_tag` and `ingestion_image_tag` before step (d). They default to `latest`,
and the repositories are `MUTABLE` because a first deployment needs to be able to
overwrite that tag.

`wait_for_steady_state = false` on both ECS services matters here. An apply does not wait
for a task to become healthy, so step (d) does not hang on a first deployment; in exchange,
an apply can report success while a task is still failing to start. The deployment circuit
breaker rolls the service back on the next refresh rather than leaving it half applied.

### Where the outputs are

```bash
terraform output                                  # everything
terraform output -raw alb_dns_name                # the host to point DNS at
terraform output -raw cognito_client_id           # what the frontend is built with
terraform output -raw api_ecr_repository_url      # already known from the naming rule
```

| Output | Use |
| --- | --- |
| `alb_dns_name`, `alb_zone_id` | The CNAME or alias target, and the hosted zone for an alias record |
| `api_ecr_repository_url`, `frontend_ecr_repository_url`, `ingestion_ecr_repository_url` | Where the three pushes go |
| `document_bucket_name` | The bucket the task role reads and writes |
| `ingestion_queue_url`, `ingestion_dead_letter_queue_url` | The queue and where messages that failed every delivery end up |
| `database_endpoint`, `database_secret_arn` | The instance and the secret holding its URL |
| `search_endpoint` | The domain endpoint the API is configured with |
| `cognito_user_pool_id`, `cognito_client_id`, `cognito_issuer`, `cognito_hosted_ui_domain` | Identity; see `docs/deployment/cognito.md` |
| `api_service_name`, `ingestion_function_name` | For `aws ecs` and `aws logs` during a deployment |

## Variables worth changing first

| Variable | Default | Changing it | Costs money | Removes a safety net |
| --- | --- | --- | --- | --- |
| `db_multi_az` | `true` | `false` runs one instance instead of a primary and a standby | Yes — roughly halves the database bill | Yes — no automatic failover |
| `db_deletion_protection` | `true` | `false` allows the instance to be destroyed; it also flips `skip_final_snapshot` and drops `final_snapshot_identifier` | No | Yes — a teardown loses the data with no final snapshot |
| `search_instance_type` | `r6g.large.search` | A smaller k-NN capable family, for example `or1.medium.search` | Yes — the domain is the most expensive resource in the stack | Performance only |
| `search_instance_count` | `2` | `1` needs `search_zone_awareness = false`, or the module raises it back to 2 | Yes, linearly | Yes, with zone awareness off — one node |
| `search_zone_awareness` | `true` | Spreads data nodes over two zones; requires an even count of at least two | Yes, at least two nodes | Yes when turned off |
| `single_nat_gateway` | `true` | `false` gives one NAT gateway per zone instead of one shared | Yes — a NAT gateway and an elastic IP per zone | Yes — a single gateway is a single point of failure for egress |
| `api_desired_count` | `2` | `1` is enough for a trial | Yes, per task | Yes — no task survives a zone failure |
| `certificate_arn` | `null` | An ACM certificate in the same region. Without it the load balancer serves HTTP | No (the certificate itself may) | Yes — without it bearer tokens travel in clear text |
| `cpu_architecture` | `X86_64` | Has to match the images that were built | No | No — but a mismatch is a task that never starts |
| `search_audit_logs` | `true` | Publishes `ES_APPLICATION_LOGS` and `AUDIT_LOGS` | Yes — CloudWatch ingestion | No; but the log resource policy is a per-account singleton, so a *second* stack in the same account may have to set it to `false` |

Two more that are cheap and worth knowing: `db_password` has no default and is the one
value that must come from outside the repository, and `alarm_topic_arn` defaults to `null`,
which creates every alarm but makes it notify nobody. Set it to the ARN of an SNS topic
that exists — the topic is not created by this stack.

## DNS and TLS

The load balancer is created with an HTTP listener on port 80. With `certificate_arn =
null` that listener forwards to the frontend target group, so the stack serves plain HTTP.
With a certificate set, an HTTPS listener on 443 appears, port 80 becomes a 301 redirect
to it, the path rules move to the HTTPS listener, and the TLS policy is
`ELBSecurityPolicy-TLS13-1-2-2021-06`.

The certificate has to exist before it can be passed in, and an ACM certificate for a
public host can only be issued once the host is known. The host is only known after the
apply. So a real deployment is:

1. `terraform apply` — read `terraform output -raw alb_dns_name`. The value looks like
   `rag-platform-production-alb-<random>.<region>.elb.amazonaws.com`; the exact name is
   not known until the apply runs.
2. Point a DNS record at it — a CNAME, or an alias record using `alb_zone_id` — and request
   a certificate for that name. DNS records and certificates are not managed here.
3. Add the same host to `auth_callback_urls` (`https://<host>/callback`) and to
   `auth_logout_urls`, and set `certificate_arn`.
4. `terraform apply` again. The certificate causes the HTTPS listener to be created and
   the listener rules to move to it.

The Cognito callback URL is the other half of the same problem. It is an input to the
`auth` module, and the load balancer's DNS name is an output of the `api` module that is
created after it — the `auth` module cannot reference a resource that does not exist yet.
Until the deployed host is added to `auth_callback_urls`, Cognito refuses the sign-in
before the request ever reaches the application. `docs/deployment/cognito.md` describes
what that failure looks like from the browser.

## What Terraform does not manage

| Not managed | Where it comes from |
| --- | --- |
| The images | Built by hand or by CI and pushed to the repositories this stack created. The task definitions and the function only name a tag |
| DNS records, and the certificate referenced by `certificate_arn` | Requested and validated outside this stack, which is why the values are variables rather than data sources |
| The SNS topic behind `alarm_topic_arn` | An account-level topic. Without it the alarms exist, record state and notify nobody |
| The OpenSearch index | Created by the application on the first write, with a `knn_vector` field sized for `APP_EMBEDDING_DIMENSIONS` |
| Bedrock model access | Granted per account and per model in the Bedrock console. The IAM policy allows `bedrock:InvokeModel`; the grant is separate |
| Database schema | There are no migrations. `init_db` creates the tables at startup, so a model change against an existing database needs the database recreated rather than upgraded |

## Teardown

```bash
cd infrastructure/terraform
terraform destroy
```

Four things refuse to go quietly, and each is deliberate:

| What | Why it blocks, and what to do |
| --- | --- |
| The RDS instance | `deletion_protection = true` by default. Set `db_deletion_protection = false` and apply before destroying, or the destroy fails. Because `skip_final_snapshot` is the inverse of that flag, turning it off also means no final snapshot is taken |
| The S3 bucket | A non-empty bucket cannot be deleted. `storage_force_destroy = false` by default; either empty the bucket first or set it to `true` for a throwaway account. Versioned objects that are not current versions still count as contents |
| The database secret | `recovery_window_in_days = 7`. The secret is scheduled for deletion rather than deleted, so recreating a stack of the same name inside that window fails until the secret is force-deleted or the window passes |
| ECR images | The repositories are deleted with the stack and their images go with them, but the lifecycle policy expires a superseded image silently while the stack is alive. `terraform state list` and the ECR console are the way to see what a destroy is about to remove |

The ALB has `enable_deletion_protection = false` on purpose: a stack that is meant to be
reproducible should not need a hand-edit before every teardown.

## Validated / not validated

Run on a local Terraform binary (v1.16.5, `darwin_arm64`), not a system install. No AWS
credentials were present at any point.

| Check | Result |
| --- | --- |
| `terraform init -backend=false` | pass — providers downloaded, `.terraform.lock.hcl` written |
| `terraform validate` | pass — configuration is internally consistent |
| `terraform fmt -check -recursive` | pass — no file needs reformatting |

`init` resolved the AWS provider to **5.100.0**, which satisfies the `~> 5.60` constraint
and is what `.terraform.lock.hcl` pins. The lock file is part of the repository, so the
same provider build is what a later `init` installs.

**Not validated**, and not claimed:

| Check | Status |
| --- | --- |
| `terraform plan` | **NOT RUN** — needs credentials and a region to read from |
| `terraform apply` (any step) | **NOT RUN** |
| Any AWS resource created by this stack | **NEVER** — no VPC, bucket, database, domain, queue, role, pool, cluster or function |
| Any image pushed to ECR | **NEVER** |
| Any Lambda deployed or invoked by SQS | **NEVER** |
| The staged apply in this document | **NOT RUN** — steps (b), (c) and (d) are derived from the dependency graph, not from an execution |
| `terraform output` values | **NEVER PRINTED** — every value in this document that is not a literal from the code is a placeholder |
| `terraform destroy` | **NOT RUN** |
| The AWS provider's acceptance of an argument value | **NOT VERIFIED** — `validate` checks the configuration, not the service. An instance class, a policy document or an argument the provider accepts locally can still be refused by AWS |

## Validating what could not be validated here

In order. Each stop is a thing to fix before continuing.

```bash
cd infrastructure/terraform
export TF_VAR_db_password='<a long random value, at least 16 characters>'

# 1. Static checks, the three that were actually run here.
terraform init -backend=false
terraform validate
terraform fmt -check -recursive

# 2. A real plan. This reaches AWS: it reads the caller identity, the region and the
#    account's existing resources, and writes nothing. The first plan is where a missing
#    permission, an unavailable instance class or a name collision shows up.
terraform plan -out=tfplan        # requires credentials

# 3. The repositories, before anything can be pushed.
terraform apply -target=module.api.aws_ecr_repository.api \
                -target=module.api.aws_ecr_repository.frontend \
                -target=module.ingestion.aws_ecr_repository.ingestion

# 4. Check the naming rule the push commands depend on.
aws ecr describe-repositories --query 'repositories[].repositoryName'

# 5. Build and push the three images (the commands under "The staged deployment this
#    stack needs"), then make sure each digest is there.
aws ecr list-images --repository-name rag-platform-production-api

# 6. The full apply, then watch a service settle rather than trusting the exit code,
#    because wait_for_steady_state is off.
terraform apply
aws ecs describe-services --cluster rag-platform-production-cluster \
  --services rag-platform-production-api --query 'services[].{status:status,running:runningCount,desired:desiredCount}'
aws logs tail /ecs/rag-platform-production-api --since 10m

# 7. The probes, through the load balancer. The second one reaching `ok` is what proves
#    the database and the vector store are reachable from the task.
curl -s http://$(terraform output -raw alb_dns_name)/health
curl -s http://$(terraform output -raw alb_dns_name)/health/ready

# 8. One ingestion, end to end: upload a document and poll it to `ready`, then ask a
#    question. Sign-in has to be working first (see docs/deployment/cognito.md) when
#    auth_backend is `cognito`.
```

The last three checks are the ones this document cannot claim: a plan that reads, an apply
that creates, and a request that reaches a running task.
