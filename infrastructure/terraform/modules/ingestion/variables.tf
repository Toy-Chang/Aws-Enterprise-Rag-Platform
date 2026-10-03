variable "name_prefix" {
  description = "Prefix for every resource name in this module."
  type        = string
}

variable "region" {
  description = "Region for the log driver configuration and the resource ARNs."
  type        = string
}

variable "vpc_id" {
  description = "VPC the function runs in."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets the function's network interfaces are created in."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group of the function. It only makes outbound calls."
  type        = string
}

variable "role_arn" {
  description = "Execution role of the function: logs, S3, SQS, OpenSearch, Bedrock and the database secret."
  type        = string
}

variable "environment" {
  description = "Environment variables for the function, named as the application declares them."
  type        = map(string)
}

variable "queue_arn" {
  description = "Queue the function consumes."
  type        = string
}

variable "queue_url" {
  description = "URL of the same queue. Only used to derive the queue name for the backlog alarm."
  type        = string
}

variable "dead_letter_queue_arn" {
  description = "Dead-letter queue of the source queue, kept for documentation of the failure path."
  type        = string
}

variable "image_tag" {
  description = "Tag of the ingestion image to run."
  type        = string
}

variable "handler" {
  description = "Handler inside the image, in module.path.function form."
  type        = string
}

variable "cpu_architecture" {
  description = "Architecture of the image: x86_64 or arm64. Has to match how the image was built."
  type        = string

  validation {
    condition     = contains(["x86_64", "arm64"], var.cpu_architecture)
    error_message = "Lambda accepts x86_64 or arm64."
  }
}

variable "memory_mb" {
  description = "Memory in MiB. Embedding is CPU bound, so more memory is also more speed."
  type        = number
}

variable "timeout_seconds" {
  description = "Timeout in seconds. Has to stay below the queue's visibility timeout."
  type        = number
}

variable "batch_size" {
  description = "Messages handed to one invocation."
  type        = number
}

variable "maximum_batching_window_seconds" {
  description = "How long the event source mapping waits to fill a batch. Zero means immediately."
  type        = number
}

variable "log_retention_days" {
  description = "CloudWatch retention for the function's log group."
  type        = number
}

variable "alarm_topic_arn" {
  description = "SNS topic for the alarms. Without it the alarms are recorded but notify nobody."
  type        = string
  default     = null
}
