variable "name_prefix" {
  description = "Prefix for every resource name in this module."
  type        = string
}

variable "region" {
  description = "Region the pool lives in. The issuer URL contains it."
  type        = string
}

variable "domain_prefix" {
  description = "Prefix of the hosted UI domain. Must be unique in the region."
  type        = string
}

variable "callback_urls" {
  description = "URLs the authorization code may be sent to. A URL that is not listed is refused by Cognito, which is the point."
  type        = list(string)

  validation {
    condition     = length(var.callback_urls) > 0
    error_message = "The app client needs at least one callback URL, or sign-in cannot complete."
  }
}

variable "logout_urls" {
  description = "URLs the browser may be sent to after signing out."
  type        = list(string)
}

variable "groups" {
  description = "User pool groups, which are the roles the API authorizes against."
  type        = list(string)

  validation {
    condition     = length(var.groups) > 0
    error_message = "Without groups nobody can hold a role."
  }

  validation {
    condition     = alltrue([for group in var.groups : contains(["viewer", "editor", "admin"], group)])
    error_message = "The application knows exactly three roles: viewer, editor and admin."
  }
}
