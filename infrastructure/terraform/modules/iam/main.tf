# The three identities the stack runs as.
#
# Two of them are ECS tasks and one is the Lambda consumer, and each gets only the calls
# its own process makes: the API publishes to the queue but never consumes it, the
# consumer consumes but only ever sends to the dead-letter queue as a failure destination,
# and neither can read the other's secret. The account id and the partition are read from
# the provider rather than written into an ARN, so the same configuration fits any account
# and any partition.

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  # ARNs the three roles share. Written once because the API and the consumer reach the
  # same documents, vectors and models -- they differ only in which SQS calls they may
  # make.
  bucket_objects_arn = "${var.bucket_arn}/*"
  search_domain_arn  = "arn:${local.partition}:es:${var.region}:${local.account_id}:domain/${var.search_domain_name}"
  search_objects_arn = "arn:${local.partition}:es:${var.region}:${local.account_id}:domain/${var.search_domain_name}/*"

  # The account field is genuinely empty for a Bedrock foundation model: model access is
  # granted per account, but the model itself is not account-owned, so the ARN has a
  # double colon. A cross-region inference profile is a different thing with a different
  # ARN -- `arn:aws:bedrock:<region>:<account>:inference-profile/<id>` -- and would need
  # its own statement if one is ever configured here.
  bedrock_model_arns = [
    "arn:${local.partition}:bedrock:${var.region}::foundation-model/${var.bedrock_embedding_model_id}",
    "arn:${local.partition}:bedrock:${var.region}::foundation-model/${var.bedrock_generation_model_id}",
  ]

  # Secrets Manager appends a six-character suffix to every secret ARN it returns, so the
  # ARN this module is handed (the one the database module output) does not match itself
  # as a resource: the policy needs the trailing wildcard to cover the real ARN. It stops
  # at one path segment deliberately -- it cannot reach another secret in a different path.
  database_secret_arn_pattern = "${var.database_secret_arn}*"

  ecs_tasks_trust = {
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  }

  lambda_trust = {
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  }
}

# --- API task role ------------------------------------------------------------------
#
# Assumed by the application container itself, so these are the calls the Python process
# makes: documents in and out of S3, ingestion work published to SQS, vectors in
# OpenSearch, embeddings and answers from Bedrock, and the database URL out of Secrets
# Manager.

resource "aws_iam_role" "api_task" {
  name        = "${var.name_prefix}-api-task"
  description = "Identity of the API container: documents, queue publishing, vectors, models and the database secret."

  assume_role_policy = jsonencode(local.ecs_tasks_trust)

  tags = {
    Name = "${var.name_prefix}-api-task"
  }
}

resource "aws_iam_role_policy" "api_task" {
  name = "${var.name_prefix}-api-task"
  role = aws_iam_role.api_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    # IAM role policies have no description of their own, so the intent lives in the
    # document: scoped to the bucket, the queue, the one search domain, the two models and
    # the database secret, with no wildcard standing in for a service.
    Statement = [
      {
        Sid    = "DocumentObjects"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        # Object actions never work on the bucket ARN itself, so the `/*` is the object
        # namespace, not a wildcard over resources.
        Resource = local.bucket_objects_arn
      },
      {
        Sid    = "DocumentBucketListing"
        Effect = "Allow"
        # ListBucket is a bucket-level action -- it cannot be granted on `/*`. The
        # application has no list endpoint today but the console and `aws s3 ls` are how
        # anyone debugs an upload, and the listing reveals nothing the task cannot already
        # read.
        Action   = "s3:ListBucket"
        Resource = var.bucket_arn
      },
      {
        Sid    = "PublishIngestionWork"
        Effect = "Allow"
        # The API only ever publishes. ReceiveMessage and DeleteMessage are deliberately
        # absent: an API task that could drain the queue would steal work from the
        # consumer and, on a failed request, delete a document's only chance of being
        # ingested.
        Action   = "sqs:SendMessage"
        Resource = var.queue_arn
      },
      {
        Sid    = "ReadWriteVectors"
        Effect = "Allow"
        # `es:ESHttp*` is the only action shape a managed domain's data plane offers: the
        # HTTP verb and path are what distinguish an index write from a search, and IAM
        # cannot see them. The scope is therefore the domain and its paths -- the domain
        # is the boundary, the individual index is not.
        Action   = "es:ESHttp*"
        Resource = [local.search_domain_arn, local.search_objects_arn]
      },
      {
        Sid    = "InvokeModels"
        Effect = "Allow"
        # InvokeModel is the single call both adapters make; no model-customization,
        # no agents, no guardrails.
        Action   = "bedrock:InvokeModel"
        Resource = local.bedrock_model_arns
      },
      {
        Sid    = "ReadDatabaseUrl"
        Effect = "Allow"
        # Read-only, and only the one secret the stack assembled. Nothing writes secrets
        # at runtime, so PutSecretValue and UpdateSecret are absent.
        Action   = "secretsmanager:GetSecretValue"
        Resource = local.database_secret_arn_pattern
      },
    ]
  })
}

# --- API execution role -------------------------------------------------------------
#
# Not the application: this is what the ECS agent does on the task's behalf before the
# container starts and while it runs -- pull the image, write the container's own logs,
# and resolve the secret injection in the task definition. The application never uses it,
# which is why it gets no S3, queue, search or model permission.

resource "aws_iam_role" "api_execution" {
  name        = "${var.name_prefix}-api-execution"
  description = "Identity of the ECS agent for the API task: image pull, log delivery and secret resolution."

  assume_role_policy = jsonencode(local.ecs_tasks_trust)

  tags = {
    Name = "${var.name_prefix}-api-execution"
  }
}

# The AWS-managed policy covers the ECR pull that is painful to hand-roll correctly (the
# token call, the layer and manifest reads) and the `logs:CreateLogStream`/`PutLogEvents`
# the agent needs. It also grants a few actions this stack does not use, which is the
# trade for not reimplementing it; everything account-specific is scoped below.
resource "aws_iam_role_policy_attachment" "api_execution_managed" {
  role       = aws_iam_role.api_execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The log groups are created by the compute modules, not here, so this module cannot name
# a log group ARN even if it wanted to: it would be a reference to a resource that does
# not exist yet, in the wrong direction. This is the one place the policies are
# intentionally broader than a single resource -- the wildcard is over
# `/ecs/${var.name_prefix}*`, this stack's own namespace, and CloudWatch Logs has no
# action here that would let one group's writer read another's.
resource "aws_iam_role_policy" "api_execution" {
  name = "${var.name_prefix}-api-execution"
  role = aws_iam_role.api_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    # Log delivery for this stack's own /ecs log groups, plus read of the database secret
    # the task definition injects.
    Statement = [
      {
        Sid    = "WriteStackLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:${local.partition}:logs:${var.region}:${local.account_id}:log-group:/ecs/${var.name_prefix}*"
      },
      {
        Sid    = "ResolveTaskSecrets"
        Effect = "Allow"
        # The agent resolves `secrets` in the task definition, so it needs the same read
        # the application has -- it does not pass the value through to the container in
        # plain text, it injects it.
        Action   = "secretsmanager:GetSecretValue"
        Resource = local.database_secret_arn_pattern
      },
    ]
  })
}

# --- Ingestion consumer role --------------------------------------------------------
#
# The Lambda behind the event source mapping. It runs inside the VPC, so it needs the ENI
# permissions as well as the log ones, and it needs exactly the calls the API makes minus
# the writing of documents: it reads the object, writes chunks and vectors, embeds and
# generates, and reads the database secret. What it adds is the queue side.

resource "aws_iam_role" "ingestion" {
  name        = "${var.name_prefix}-ingestion"
  description = "Identity of the ingestion Lambda: consumes the queue, reads documents, writes vectors, invokes models."

  assume_role_policy = jsonencode(local.lambda_trust)

  tags = {
    Name = "${var.name_prefix}-ingestion"
  }
}

resource "aws_iam_role_policy_attachment" "ingestion_basic_execution" {
  role       = aws_iam_role.ingestion.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# The ENI permissions are what a VPC-attached function needs to create and delete the
# network interface it runs behind. Without them the function cannot start at all.
resource "aws_iam_role_policy_attachment" "ingestion_vpc_access" {
  role       = aws_iam_role.ingestion.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaENIManagementAccess"
}

resource "aws_iam_role_policy" "ingestion" {
  name = "${var.name_prefix}-ingestion"
  role = aws_iam_role.ingestion.id

  policy = jsonencode({
    Version = "2012-10-17"
    # Queue consumption and DLQ failure forwarding, document reads and writes, vectors,
    # models and the database secret.
    Statement = [
      {
        Sid    = "DocumentObjects"
        Effect = "Allow"
        # PutObject is here for the derived artefacts ingestion may write back; Delete is
        # absent because a consumer must never remove the source document.
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = local.bucket_objects_arn
      },
      {
        Sid    = "ListDocumentBucket"
        Effect = "Allow"
        # Only so an unreadable key is diagnosable from the function; no bulk listing.
        Action   = "s3:ListBucket"
        Resource = var.bucket_arn
      },
      {
        Sid    = "ConsumeIngestionQueue"
        Effect = "Allow"
        # The whole consumer contract: receive a batch, extend the visibility timeout of a
        # message it is still working on (ChangeMessageVisibility), and delete only the
        # messages it reports as handled. PurgeQueue is absent -- one bug there would
        # discard queued work irrecoverably.
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = var.queue_arn
      },
      {
        Sid    = "ForwardPoisonMessages"
        Effect = "Allow"
        # The event source mapping names the DLQ as its failure destination, and the
        # service does that send with this role. Send only: a consumer that could read the
        # DLQ would be able to consume the evidence of its own failures.
        Action   = "sqs:SendMessage"
        Resource = var.dead_letter_queue_arn
      },
      {
        Sid      = "ReadWriteVectors"
        Effect   = "Allow"
        Action   = "es:ESHttp*"
        Resource = [local.search_domain_arn, local.search_objects_arn]
      },
      {
        Sid    = "InvokeModels"
        Effect = "Allow"
        # The consumer is the only thing that embeds, so this is where the embedding model
        # is really used; the generation model is here because ingestion and query share
        # the same adapters and configuration.
        Action   = "bedrock:InvokeModel"
        Resource = local.bedrock_model_arns
      },
      {
        Sid      = "ReadDatabaseUrl"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = local.database_secret_arn_pattern
      },
    ]
  })
}
