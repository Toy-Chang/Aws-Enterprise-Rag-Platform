variable "name_prefix" {
  description = "Prefix for every resource name in this module."
  type        = string
}

variable "region" {
  description = "Region for the log driver configuration and the resource ARNs."
  type        = string
}

variable "vpc_id" {
  description = "VPC the target groups belong to."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets the tasks run in. No task has a public address."
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "Public subnets the load balancer is placed in. At least two for an ALB."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_ids) >= 2
    error_message = "An application load balancer needs at least two subnets in different zones."
  }
}

variable "security_group_id" {
  description = "Security group of the tasks."
  type        = string
}

variable "alb_security_group_id" {
  description = "Security group of the load balancer."
  type        = string
}

variable "task_role_arn" {
  description = "Role the application code assumes: S3, SQS send, OpenSearch, Bedrock, the database secret."
  type        = string
}

variable "execution_role_arn" {
  description = "Role the ECS agent assumes: image pull, logs and the secret the task definition references."
  type        = string
}

variable "environment" {
  description = "Plain environment variables for the API container, named as the application declares them."
  type        = map(string)
}

variable "secrets" {
  description = "Environment variables resolved from Secrets Manager, as name => valueFrom."
  type        = map(string)
}

variable "image_tag" {
  description = "Tag of the API image to run."
  type        = string
}

variable "frontend_image_tag" {
  description = "Tag of the frontend image to run."
  type        = string
}

variable "container_port" {
  description = "Port the API container listens on. Also injected as APP_PORT so the process and the target group agree."
  type        = number
}

variable "cpu" {
  description = "Fargate CPU units for the API task (1024 = 1 vCPU)."
  type        = number
}

variable "memory_mb" {
  description = "Fargate memory for the API task in MiB."
  type        = number
}

variable "desired_count" {
  description = "Number of API tasks to start with. Autoscaling owns it afterwards."
  type        = number
}

variable "min_capacity" {
  description = "Lower bound for API autoscaling."
  type        = number
}

variable "max_capacity" {
  description = "Upper bound for API autoscaling."
  type        = number
}

variable "frontend_cpu" {
  description = "Fargate CPU units for the frontend task."
  type        = number
}

variable "frontend_memory_mb" {
  description = "Fargate memory for the frontend task in MiB."
  type        = number
}

variable "frontend_desired_count" {
  description = "Number of frontend tasks to start with."
  type        = number
}

variable "frontend_min_capacity" {
  description = "Lower bound for frontend autoscaling."
  type        = number
}

variable "frontend_max_capacity" {
  description = "Upper bound for frontend autoscaling."
  type        = number
}

variable "certificate_arn" {
  description = "ACM certificate for the HTTPS listener. Without it the load balancer serves plain HTTP."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "CloudWatch retention for the task log groups."
  type        = number
}

variable "alarm_topic_arn" {
  description = "SNS topic for the alarms. Without it the alarms are recorded but notify nobody."
  type        = string
  default     = null
}

variable "cpu_architecture" {
  description = "Architecture of the image: X86_64 or ARM64. Has to match how the image was built."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "Fargate accepts X86_64 or ARM64."
  }
}
