variable "name_prefix" {
  description = "Prefix every resource name in this module starts with, so one account can hold several copies of the stack."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "How long a received message stays invisible to other consumers. Has to comfortably exceed one document's ingestion, or a document still running when it expires is delivered again and processed twice."
  type        = number
}

variable "message_retention_seconds" {
  description = "How long an unconsumed message is kept on the main queue before SQS discards it."
  type        = number
}

variable "max_receive_count" {
  description = "Deliveries after which a message is moved to the dead-letter queue instead of being handed out again."
  type        = number
}

variable "alarm_topic_arn" {
  description = "SNS topic the dead-letter alarm notifies. Null creates the alarm without actions, so it reports state but reaches nobody."
  type        = string
  default     = null
}
