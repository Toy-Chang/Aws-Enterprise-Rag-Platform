# Version constraints for the whole stack.
#
# The AWS provider is pinned to a minor line rather than to an exact patch: a patch
# upgrade should not need a code change, and a minor upgrade should be a deliberate
# commit that has been re-validated.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Remote state is not configured here on purpose: a committed backend block would make
  # `terraform init` fail for anyone without that bucket. Create the bucket for your own
  # account and uncomment the block (or pass it with `-backend-config`).
  #
  # backend "s3" {
  #   bucket       = "my-terraform-state"
  #   key          = "rag-platform/terraform.tfstate"
  #   region       = "eu-west-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}
