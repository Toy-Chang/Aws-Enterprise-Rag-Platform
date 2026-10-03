variable "name_prefix" {
  description = "Prefix for every resource name in this module."
  type        = string
}

variable "vpc_id" {
  description = "VPC the database lives in. Used for documentation and future options."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets the database may run in. RDS needs at least two for a subnet group."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "Give at least two subnets: RDS refuses a subnet group with fewer."
  }
}

variable "security_group_id" {
  description = "Security group allowing PostgreSQL from the API tasks and the consumer. Owned by the network module."
  type        = string
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
}

variable "allocated_storage_gb" {
  description = "Initial storage in GiB."
  type        = number
}

variable "max_allocated_storage_gb" {
  description = "Ceiling for storage autoscaling in GiB."
  type        = number
}

variable "engine_version" {
  description = "PostgreSQL engine version."
  type        = string
}

variable "database_name" {
  description = "Database created inside the instance."
  type        = string
}

variable "master_username" {
  description = "Master user of the instance."
  type        = string
}

variable "master_password" {
  description = "Master password. Supplied through a variable so it never reaches the repository."
  type        = string
  sensitive   = true
}

variable "multi_az" {
  description = "Run a standby in a second zone so a failure fails over automatically."
  type        = bool
}

variable "deletion_protection" {
  description = "Refuse to delete the instance until this is turned off. Also decides whether a final snapshot is taken."
  type        = bool
}

variable "backup_retention_days" {
  description = "Automated backup retention in days. Zero disables backups."
  type        = number

  validation {
    condition     = var.backup_retention_days >= 0 && var.backup_retention_days <= 35
    error_message = "RDS accepts 0 to 35 days of automated backups."
  }
}
