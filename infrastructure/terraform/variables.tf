# Every input the stack takes. Defaults describe a production-shaped deployment: two
# tasks behind a load balancer, a Multi-AZ database, a two-node search domain and a
# queue that can be retried. The expensive ones are called out in the README with a
# cheaper value for a trial run.

# --- Identity ---------------------------------------------------------------------

variable "project" {
  description = "Name of the platform. Used as the prefix of every resource name."
  type        = string
  default     = "rag-platform"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.project))
    error_message = "Use 3 to 25 lower-case letters, digits and dashes, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment environment. Part of every resource name, so one account can hold several."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "The application only accepts development, staging or production."
  }
}

variable "region" {
  description = "AWS region for every resource in the stack."
  type        = string
  default     = "eu-west-1"

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]$", var.region))
    error_message = "Use an AWS region name such as eu-west-1."
  }
}

variable "log_level" {
  description = "Application log level (CRITICAL, ERROR, WARNING, INFO or DEBUG)."
  type        = string
  default     = "INFO"
}

variable "log_retention_days" {
  description = "CloudWatch retention for the API and consumer log groups."
  type        = number
  default     = 30
}

# --- Network ----------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block of the VPC. Subnets are carved out of it with cidrsubnet."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones to spread the stack over. Empty means the first two of the region."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.availability_zones) < 2 || length(distinct(var.availability_zones)) >= 2
    error_message = "Give at least two distinct zones, or leave the list empty."
  }
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway instead of one per zone. Cheaper, and a single point of failure for egress."
  type        = bool
  default     = true
}

# --- Documents --------------------------------------------------------------------

variable "storage_force_destroy" {
  description = "Allow Terraform to delete a non-empty document bucket. Keep false outside throwaway accounts."
  type        = bool
  default     = false
}

variable "storage_expire_noncurrent_days" {
  description = "Days after which a superseded object version is deleted."
  type        = number
  default     = 30
}

# --- Database ---------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class. db.t4g.medium is the smallest sensible start."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  description = "Initial database storage in GiB."
  type        = number
  default     = 100
}

variable "db_max_allocated_storage_gb" {
  description = "Ceiling for storage autoscaling in GiB. Must not be lower than the initial size."
  type        = number
  default     = 200
}

variable "db_engine_version" {
  description = "PostgreSQL engine version for RDS."
  type        = string
  default     = "16.4"
}

variable "db_name" {
  description = "Name of the application database created inside the instance."
  type        = string
  default     = "rag"
}

variable "db_master_username" {
  description = "Master user of the RDS instance."
  type        = string
  default     = "rag_admin"
}

variable "db_password" {
  description = "Master password for RDS. Supply it through TF_VAR_db_password or a tfvars file that is never committed."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.db_password) >= 16
    error_message = "Use at least 16 characters: RDS refuses shorter master passwords."
  }
}

variable "db_multi_az" {
  description = "Run a standby replica in a second zone. Costs double and is what makes a failover automatic."
  type        = bool
  default     = true
}

variable "db_deletion_protection" {
  description = "Refuse to delete the instance until this is turned off. Keep true for anything real."
  type        = bool
  default     = true
}

variable "db_backup_retention_days" {
  description = "Automated backup retention in days. Zero disables backups."
  type        = number
  default     = 7
}

# --- Vector search ----------------------------------------------------------------

variable "search_instance_type" {
  description = "OpenSearch data node type. Needs to be a k-NN capable family."
  type        = string
  default     = "r6g.large.search"
}

variable "search_instance_count" {
  description = "Number of data nodes."
  type        = number
  default     = 2
}

variable "search_engine_version" {
  description = "OpenSearch engine version, for example OpenSearch_2.13."
  type        = string
  default     = "OpenSearch_2.13"
}

variable "search_volume_size_gb" {
  description = "EBS volume size per data node in GiB."
  type        = number
  default     = 100
}

variable "search_zone_awareness" {
  description = "Spread data nodes over two zones. Needs an even number of nodes."
  type        = bool
  default     = true
}

variable "search_audit_logs" {
  description = "Publish the search domain's application and audit logs to CloudWatch. The log resource policy it needs is a per-account singleton, so a second stack in the same account may have to turn this off."
  type        = bool
  default     = true
}

variable "opensearch_index" {
  description = "Index the application writes chunks and vectors into."
  type        = string
  default     = "rag-chunks"
}

# --- Ingestion queue --------------------------------------------------------------

variable "queue_visibility_timeout_seconds" {
  description = "How long a received message stays invisible. Must comfortably exceed one document's ingestion."
  type        = number
  default     = 900
}

variable "queue_message_retention_seconds" {
  description = "How long an unconsumed message is kept. Four days by default."
  type        = number
  default     = 345600
}

variable "queue_max_receive_count" {
  description = "Deliveries before a message is moved to the dead-letter queue."
  type        = number
  default     = 3
}

# --- Models -----------------------------------------------------------------------

variable "embedding_dimensions" {
  description = "Vector width. Must match the embedding model and the existing index mapping."
  type        = number
  default     = 1024
}

variable "bedrock_embedding_model_id" {
  description = "Bedrock embedding model."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "bedrock_generation_model_id" {
  description = "Bedrock generation model used when generation_provider is bedrock."
  type        = string
  default     = "amazon.nova-lite-v1:0"
}

variable "generation_provider" {
  description = "Answer generator: bedrock or local. Local is extractive and needs no model access."
  type        = string
  default     = "bedrock"

  validation {
    condition     = contains(["bedrock", "local"], var.generation_provider)
    error_message = "The application accepts bedrock or local."
  }
}

variable "rerank_enabled" {
  description = "Turn on the lexical reranker. Measured to change nothing on the sample corpus, so it is off."
  type        = bool
  default     = false
}

# --- Authentication ---------------------------------------------------------------

variable "auth_domain_prefix" {
  description = "Prefix of the Cognito hosted UI domain. Must be globally unique; empty derives one from the project and environment."
  type        = string
  default     = ""
}

variable "auth_callback_urls" {
  description = "OAuth callback URLs the app client accepts."
  type        = list(string)
  default     = ["http://localhost:5173/callback"]
}

variable "auth_logout_urls" {
  description = "Sign-out URLs the app client accepts."
  type        = list(string)
  default     = ["http://localhost:5173/"]
}

variable "auth_groups" {
  description = "User pool groups, which are the roles the application authorizes against."
  type        = list(string)
  default     = ["viewer", "editor", "admin"]

  validation {
    condition     = alltrue([for group in var.auth_groups : contains(["viewer", "editor", "admin"], group)])
    error_message = "The application knows exactly three roles: viewer, editor and admin."
  }
}

# --- API service ------------------------------------------------------------------

variable "api_image_tag" {
  description = "Image tag the API task definition runs. The image itself is built and pushed outside Terraform."
  type        = string
  default     = "latest"
}

variable "api_cpu" {
  description = "Fargate CPU units for the API task (256 = 0.25 vCPU)."
  type        = number
  default     = 1024
}

variable "api_memory_mb" {
  description = "Fargate memory for the API task in MiB."
  type        = number
  default     = 2048
}

variable "api_desired_count" {
  description = "Number of API tasks to run."
  type        = number
  default     = 2
}

variable "api_min_capacity" {
  description = "Lower bound for API autoscaling."
  type        = number
  default     = 1
}

variable "api_max_capacity" {
  description = "Upper bound for API autoscaling."
  type        = number
  default     = 4
}

variable "api_port" {
  description = "Port the API container listens on. The application defaults to 8000."
  type        = number
  default     = 8000
}

# --- Frontend service -------------------------------------------------------------

variable "frontend_image_tag" {
  description = "Image tag the frontend task definition runs."
  type        = string
  default     = "latest"
}

variable "frontend_cpu" {
  description = "Fargate CPU units for the frontend task. nginx needs very little."
  type        = number
  default     = 256
}

variable "frontend_memory_mb" {
  description = "Fargate memory for the frontend task in MiB."
  type        = number
  default     = 512
}

variable "frontend_desired_count" {
  description = "Number of frontend tasks to run."
  type        = number
  default     = 1
}

variable "frontend_min_capacity" {
  description = "Lower bound for frontend autoscaling."
  type        = number
  default     = 1
}

variable "frontend_max_capacity" {
  description = "Upper bound for frontend autoscaling."
  type        = number
  default     = 3
}

variable "certificate_arn" {
  description = "ACM certificate for the HTTPS listener. Without it the load balancer serves plain HTTP, which is for trials only."
  type        = string
  default     = null
}

# --- Ingestion consumer -----------------------------------------------------------

variable "ingestion_image_tag" {
  description = "Image tag the ingestion Lambda runs."
  type        = string
  default     = "latest"
}

variable "ingestion_memory_mb" {
  description = "Lambda memory in MiB. Ingestion is CPU bound while embedding, so more memory is also more speed."
  type        = number
  default     = 1024
}

variable "ingestion_timeout_seconds" {
  description = "Lambda timeout in seconds. Has to be shorter than the queue visibility timeout."
  type        = number
  default     = 300

  validation {
    condition     = var.ingestion_timeout_seconds < var.queue_visibility_timeout_seconds
    error_message = "A function that outlives the visibility timeout has its document processed twice."
  }
}

variable "ingestion_batch_size" {
  description = "Messages handed to one invocation."
  type        = number
  default     = 5
}

variable "ingestion_max_batching_window_seconds" {
  description = "How long the event source mapping waits to fill a batch. Zero means as soon as one message arrives."
  type        = number
  default     = 0
}

variable "alarm_topic_arn" {
  description = "SNS topic that receives the stack's alarms. Without it the alarms exist but notify nobody."
  type        = string
  default     = null
}

variable "cpu_architecture" {
  description = "Architecture the images are built for: X86_64 or ARM64. Has to match how `docker build` ran -- an Apple silicon machine produces arm64 unless told otherwise."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "Both Fargate and Lambda accept X86_64/x86_64 or ARM64/arm64."
  }
}

variable "ingestion_handler" {
  description = "Handler inside the ingestion image. The image is the API image, whose CMD starts the web server, so the handler is named explicitly."
  type        = string
  default     = "app.aws.handler.handler"
}
