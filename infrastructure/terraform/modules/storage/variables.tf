variable "name_prefix" {
  description = "Prefix for every resource name in this module."
  type        = string
}

variable "force_destroy" {
  description = "Allow Terraform to delete a non-empty bucket. Keep false outside a throwaway account."
  type        = bool
}

variable "expire_noncurrent_versions_days" {
  description = "Days after which a superseded object version is deleted."
  type        = number

  validation {
    condition     = var.expire_noncurrent_versions_days >= 1
    error_message = "Keep superseded versions for at least a day; zero would delete them immediately."
  }
}
