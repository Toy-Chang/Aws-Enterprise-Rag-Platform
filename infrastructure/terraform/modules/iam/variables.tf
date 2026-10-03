variable "name_prefix" {
  description = "Prefix of every role and policy name in this module, so one account can hold several copies of the stack."
  type        = string
}

variable "region" {
  description = "Region used to build the ARNs of the regional services: OpenSearch, Bedrock, CloudWatch Logs."
  type        = string
}

variable "bucket_arn" {
  description = "ARN of the bucket holding the documents. Object actions are scoped to the bucket's `/*` object namespace, listing to the bucket itself."
  type        = string
}

variable "queue_arn" {
  description = "ARN of the ingestion queue the API publishes to and the consumer receives from."
  type        = string
}

variable "dead_letter_queue_arn" {
  description = "ARN of the dead-letter queue the event source mapping forwards poison messages to."
  type        = string
}

variable "database_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the database URL. It is matched with a trailing wildcard, because Secrets Manager appends a random suffix to the ARN it returns."
  type        = string
}

variable "search_domain_name" {
  description = "Name of the OpenSearch domain, which is what its ARN is built from: the module is given the name, not the domain resource."
  type        = string
}

variable "bedrock_embedding_model_id" {
  description = "Bedrock embedding model the ingestion consumer invokes, for example amazon.titan-embed-text-v2:0."
  type        = string
}

variable "bedrock_generation_model_id" {
  description = "Bedrock generation model the API invokes when it answers, for example amazon.nova-lite-v1:0."
  type        = string
}
