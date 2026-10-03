variable "name_prefix" {
  description = "Prefix for the resources around the domain, such as its log group and policy."
  type        = string
}

variable "domain_name" {
  description = "Name of the OpenSearch domain. Has to be unique in the account."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,27}$", var.domain_name))
    error_message = "OpenSearch domain names are 3 to 28 lower-case letters, digits and dashes, starting with a letter."
  }
}

variable "subnet_ids" {
  description = "Private subnets the domain's nodes run in."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group allowing HTTPS from the API tasks and the consumer. Owned by the network module."
  type        = string
}

variable "allowed_principal_arns" {
  description = "IAM roles allowed to call the domain: the API task role and the consumer role."
  type        = list(string)

  validation {
    condition     = length(var.allowed_principal_arns) > 0
    error_message = "The access policy has to name at least one principal, or the domain is unusable."
  }
}

variable "instance_type" {
  description = "Data node instance type. Has to be a k-NN capable family."
  type        = string
}

variable "instance_count" {
  description = "Number of data nodes. Two or more when zone awareness is on."
  type        = number
}

variable "engine_version" {
  description = "OpenSearch engine version, for example OpenSearch_2.13."
  type        = string
}

variable "volume_size_gb" {
  description = "EBS volume size per data node in GiB."
  type        = number
}

variable "zone_awareness_enabled" {
  description = "Spread the data nodes over two zones."
  type        = bool
}

variable "enable_audit_logs" {
  description = "Publish application and audit logs to CloudWatch. Off by default: the log resource policy it needs is a per-account singleton."
  type        = bool
}

variable "log_retention_days" {
  description = "CloudWatch retention for the domain logs."
  type        = number
}
