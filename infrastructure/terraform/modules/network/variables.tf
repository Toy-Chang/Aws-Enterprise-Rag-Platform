variable "name_prefix" {
  description = "Prefix for every resource name in this module."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC. Subnets are carved out of it with cidrsubnet."
  type        = string

  validation {
    condition     = can(cidrsubnet(var.vpc_cidr, 8, 0))
    error_message = "The VPC CIDR has to be large enough to be split into /24 subnets."
  }
}

variable "availability_zones" {
  description = "Availability zones to spread the subnets over. At least two, for a failover."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "Give at least two availability zones."
  }
}

variable "single_nat_gateway" {
  description = "Create one NAT gateway instead of one per zone. Cheaper, and a single point of failure for egress."
  type        = bool
}
