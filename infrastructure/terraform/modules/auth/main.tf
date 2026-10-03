# Cognito: the user pool the API verifies tokens against, and the app client the SPA signs
# in with.
#
# The sign-in flow is the authorization-code flow with PKCE, which is what a browser can
# do without a client secret: the frontend is a public client, and a secret shipped in a
# JavaScript bundle is not a secret. The groups are the roles the API authorizes against
# (`viewer`, `editor`, `admin`), so a user's permissions are managed where the user is.

resource "aws_cognito_user_pool" "this" {
  name = "${var.name_prefix}-users"

  # An internal tool: an administrator creates the account, and the address is the
  # identifier. Self-service sign-up would let anyone with an email address create a
  # principal, and the pool would be the only thing between them and the corpus.
  username_attributes = ["email"]
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  auto_verified_attributes = ["email"]
  mfa_configuration        = "OPTIONAL"

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # The token the API reads is the access token, and the claims it authorizes against are
  # read from the signed token itself; nothing here depends on a mutable user attribute.
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 5
      max_length = 254
    }
  }

  tags = { Name = "${var.name_prefix}-users" }
}

# A public client: no secret, and PKCE instead. The access token is short lived because it
# cannot be revoked once issued; the refresh token is what keeps a session usable.
resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.name_prefix}-web"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  allowed_oauth_flows_user_pool_client = true
  supported_identity_providers         = ["COGNITO"]

  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # A signed-out token stays dead instead of remaining valid until it expires.
  enable_token_revocation = true

  # Answering "user does not exist" differently from "wrong password" tells an attacker
  # which addresses are real.
  prevent_user_existence_errors = "ENABLED"

  # The API needs the groups claim, and the default read/write set is enough to sign in
  # and read the address; nothing else is exposed to the browser.
  read_attributes  = ["email", "email_verified"]
  write_attributes = ["email"]
}

# The hosted UI. Cognito requires the prefix to be unique across the region, so a
# collision is a configuration change (var.domain_prefix), not a code change.
resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

# One group per role. Precedence only matters when a group maps to an IAM role in an
# identity pool, which this stack does not use; the values are still ordered so an admin
# outranks an editor if that ever changes.
resource "aws_cognito_user_group" "this" {
  for_each = toset(var.groups)

  name         = each.value
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Members of this group act as ${each.value}s in the platform."
  precedence   = local.group_precedence[each.value]
}

locals {
  group_precedence = {
    admin  = 10
    editor = 20
    viewer = 30
  }
}
