# The whole stack, wired from modules in dependency order.
#
# Nothing here is a placeholder: every module below creates real resources, and the
# references between them are what make the ordering explicit -- the network before the
# database, the roles before the search domain's access policy, the queue before the
# function that consumes it.

module "network" {
  source = "./modules/network"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  availability_zones = local.availability_zones
  single_nat_gateway = var.single_nat_gateway
}

module "storage" {
  source = "./modules/storage"

  name_prefix                     = local.name_prefix
  force_destroy                   = var.storage_force_destroy
  expire_noncurrent_versions_days = var.storage_expire_noncurrent_days
}

module "database" {
  source = "./modules/database"

  name_prefix              = local.name_prefix
  vpc_id                   = module.network.vpc_id
  subnet_ids               = module.network.private_subnet_ids
  security_group_id        = module.network.database_security_group_id
  instance_class           = var.db_instance_class
  allocated_storage_gb     = var.db_allocated_storage_gb
  max_allocated_storage_gb = var.db_max_allocated_storage_gb
  engine_version           = var.db_engine_version
  database_name            = var.db_name
  master_username          = var.db_master_username
  master_password          = var.db_password
  multi_az                 = var.db_multi_az
  deletion_protection      = var.db_deletion_protection
  backup_retention_days    = var.db_backup_retention_days
}

module "queue" {
  source = "./modules/queue"

  name_prefix                = local.name_prefix
  visibility_timeout_seconds = var.queue_visibility_timeout_seconds
  message_retention_seconds  = var.queue_message_retention_seconds
  max_receive_count          = var.queue_max_receive_count
  alarm_topic_arn            = var.alarm_topic_arn
}

module "iam" {
  source = "./modules/iam"

  name_prefix                 = local.name_prefix
  region                      = var.region
  bucket_arn                  = module.storage.bucket_arn
  queue_arn                   = module.queue.queue_arn
  dead_letter_queue_arn       = module.queue.dead_letter_queue_arn
  database_secret_arn         = module.database.secret_arn
  search_domain_name          = local.search_domain_name
  bedrock_embedding_model_id  = var.bedrock_embedding_model_id
  bedrock_generation_model_id = var.bedrock_generation_model_id
}

module "search" {
  source = "./modules/search"

  name_prefix            = local.name_prefix
  domain_name            = local.search_domain_name
  subnet_ids             = module.network.private_subnet_ids
  security_group_id      = module.network.search_security_group_id
  allowed_principal_arns = [module.iam.api_task_role_arn, module.iam.ingestion_role_arn]
  instance_type          = var.search_instance_type
  instance_count         = var.search_instance_count
  engine_version         = var.search_engine_version
  volume_size_gb         = var.search_volume_size_gb
  zone_awareness_enabled = var.search_zone_awareness
  enable_audit_logs      = var.search_audit_logs
  log_retention_days     = var.log_retention_days
}

module "auth" {
  source = "./modules/auth"

  name_prefix = local.name_prefix
  region      = var.region
  # Cognito requires the hosted UI prefix to be unique across the region; a collision is
  # fixed by setting auth_domain_prefix, not by editing the module.
  domain_prefix = var.auth_domain_prefix != "" ? var.auth_domain_prefix : "${local.name_prefix}-auth"
  callback_urls = var.auth_callback_urls
  logout_urls   = var.auth_logout_urls
  groups        = var.auth_groups
  # The load balancer's DNS name is an output, not an input: the app client's callback
  # URLs cannot reference a resource that this module is created before. Add the
  # hostname to `auth_callback_urls` and apply again once it is known.
}

module "api" {
  source = "./modules/api"

  name_prefix            = local.name_prefix
  region                 = var.region
  vpc_id                 = module.network.vpc_id
  subnet_ids             = module.network.private_subnet_ids
  public_subnet_ids      = module.network.public_subnet_ids
  security_group_id      = module.network.api_security_group_id
  alb_security_group_id  = module.network.alb_security_group_id
  task_role_arn          = module.iam.api_task_role_arn
  execution_role_arn     = module.iam.api_execution_role_arn
  environment            = local.app_environment
  secrets                = local.app_secrets
  image_tag              = var.api_image_tag
  frontend_image_tag     = var.frontend_image_tag
  container_port         = var.api_port
  cpu                    = var.api_cpu
  memory_mb              = var.api_memory_mb
  desired_count          = var.api_desired_count
  min_capacity           = var.api_min_capacity
  max_capacity           = var.api_max_capacity
  frontend_cpu           = var.frontend_cpu
  frontend_memory_mb     = var.frontend_memory_mb
  frontend_desired_count = var.frontend_desired_count
  frontend_min_capacity  = var.frontend_min_capacity
  frontend_max_capacity  = var.frontend_max_capacity
  certificate_arn        = var.certificate_arn
  log_retention_days     = var.log_retention_days
  alarm_topic_arn        = var.alarm_topic_arn
  cpu_architecture       = var.cpu_architecture
}

module "ingestion" {
  source = "./modules/ingestion"

  name_prefix       = local.name_prefix
  region            = var.region
  vpc_id            = module.network.vpc_id
  subnet_ids        = module.network.private_subnet_ids
  security_group_id = module.network.lambda_security_group_id
  role_arn          = module.iam.ingestion_role_arn
  # The consumer is told where the secret is, not what it contains: a Lambda has no
  # equivalent of an ECS `secrets` entry that resolves `valueFrom` into an environment
  # variable, so the function reads the URL itself at cold start.
  environment = merge(local.app_environment, {
    APP_DATABASE_SECRET_ARN = module.database.secret_arn
  })
  queue_arn                       = module.queue.queue_arn
  queue_url                       = module.queue.queue_url
  dead_letter_queue_arn           = module.queue.dead_letter_queue_arn
  image_tag                       = var.ingestion_image_tag
  handler                         = var.ingestion_handler
  cpu_architecture                = lower(var.cpu_architecture)
  memory_mb                       = var.ingestion_memory_mb
  timeout_seconds                 = var.ingestion_timeout_seconds
  batch_size                      = var.ingestion_batch_size
  maximum_batching_window_seconds = var.ingestion_max_batching_window_seconds
  log_retention_days              = var.log_retention_days
  alarm_topic_arn                 = var.alarm_topic_arn
}
