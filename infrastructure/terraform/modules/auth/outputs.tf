output "user_pool_id" {
  description = "User pool the API is configured with (APP_COGNITO_USER_POOL_ID)."
  value       = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  description = "ARN of the user pool."
  value       = aws_cognito_user_pool.this.arn
}

output "client_id" {
  description = "App client id (APP_COGNITO_CLIENT_ID, and the frontend's VITE_COGNITO_CLIENT_ID)."
  value       = aws_cognito_user_pool_client.web.id
}

output "issuer" {
  description = "Issuer URL an accepted token has to carry. The API verifies exactly this value."
  value       = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}

output "domain" {
  description = "Hosted UI domain the browser is sent to for sign-in."
  value       = aws_cognito_user_pool_domain.this.domain
}

output "hosted_ui_url" {
  description = "Fully qualified hosted UI base URL, for a manual sign-in test."
  value       = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.region}.amazoncognito.com"
}

output "jwks_uri" {
  description = "Key document the API fetches to verify a token's signature."
  value       = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.this.id}/.well-known/jwks.json"
}
