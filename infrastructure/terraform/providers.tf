provider "aws" {
  region = var.region

  # Tags applied to every taggable resource, so a cost report or an inventory query can
  # attribute anything in this stack without each resource repeating the metadata.
  default_tags {
    tags = local.common_tags
  }
}

locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # One prefix for every resource name, so the stack can be created twice in one account
  # by changing only `environment`.
  name_prefix = "${var.project}-${var.environment}"

  # Two availability zones by default. Explicit zones are allowed because not every
  # region offers the same letters, and deriving them from the region name (rather than
  # a data source) keeps the configuration readable and plan-light.
  availability_zones = (
    length(var.availability_zones) > 0
    ? var.availability_zones
    : ["${var.region}a", "${var.region}b"]
  )

  search_domain_name = "${local.name_prefix}-search"

  # Every setting the API and the ingestion consumer read, named exactly as the
  # application declares them in backend/app/core/config.py. The two processes run with
  # the same configuration, which is what makes "a document is ingested the same way
  # whoever asked" true in a deployment and not just in a test.
  #
  # `ingestion_worker_enabled = false` because the queue drives ingestion: running the
  # polling worker as well would ingest the same document twice.
  app_environment = {
    APP_ENVIRONMENT                 = var.environment
    APP_LOG_FORMAT                  = "json"
    APP_LOG_LEVEL                   = var.log_level
    APP_HOST                        = "0.0.0.0"
    APP_STORAGE_BACKEND             = "s3"
    APP_S3_BUCKET                   = module.storage.bucket_name
    APP_S3_REGION                   = var.region
    APP_EMBEDDING_PROVIDER          = "bedrock"
    APP_EMBEDDING_DIMENSIONS        = tostring(var.embedding_dimensions)
    APP_BEDROCK_REGION              = var.region
    APP_BEDROCK_EMBEDDING_MODEL_ID  = var.bedrock_embedding_model_id
    APP_GENERATION_PROVIDER         = var.generation_provider
    APP_BEDROCK_GENERATION_MODEL_ID = var.bedrock_generation_model_id
    APP_VECTOR_STORE_BACKEND        = "opensearch"
    APP_OPENSEARCH_ENDPOINT         = "https://${module.search.endpoint}"
    APP_OPENSEARCH_REGION           = var.region
    APP_OPENSEARCH_INDEX            = var.opensearch_index
    APP_QUEUE_BACKEND               = "sqs"
    APP_SQS_QUEUE_URL               = module.queue.queue_url
    APP_SQS_REGION                  = var.region
    APP_AUTH_BACKEND                = "cognito"
    APP_COGNITO_USER_POOL_ID        = module.auth.user_pool_id
    APP_COGNITO_CLIENT_ID           = module.auth.client_id
    APP_COGNITO_REGION              = var.region
    APP_INGESTION_WORKER_ENABLED    = "false"
    APP_RERANK_ENABLED              = tostring(var.rerank_enabled)
  }

  # The database URL is a secret because it carries the password. Injecting it from
  # Secrets Manager rather than from an environment variable keeps it out of the task
  # definition, out of `terraform plan` output and out of the console.
  app_secrets = {
    APP_DATABASE_URL = "${module.database.secret_arn}:url::"
  }
}
