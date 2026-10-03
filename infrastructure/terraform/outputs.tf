# What a caller needs to reach the stack, or to push an image to it.

output "alb_dns_name" {
  description = "Public DNS name of the load balancer. Point a CNAME at it."
  value       = module.api.alb_dns_name
}

output "alb_zone_id" {
  description = "Hosted zone id of the load balancer, for an alias record."
  value       = module.api.alb_zone_id
}

output "api_ecr_repository_url" {
  description = "Push the API image here, then set api_image_tag."
  value       = module.api.api_repository_url
}

output "frontend_ecr_repository_url" {
  description = "Push the frontend image here, then set frontend_image_tag."
  value       = module.api.frontend_repository_url
}

output "ingestion_ecr_repository_url" {
  description = "Push the ingestion image here, then set ingestion_image_tag."
  value       = module.ingestion.repository_url
}

output "document_bucket_name" {
  description = "Bucket holding the uploaded documents."
  value       = module.storage.bucket_name
}

output "ingestion_queue_url" {
  description = "Queue the API publishes ingestion work to."
  value       = module.queue.queue_url
}

output "ingestion_dead_letter_queue_url" {
  description = "Queue that collects messages no delivery could process."
  value       = module.queue.dead_letter_queue_url
}

output "database_endpoint" {
  description = "RDS endpoint the API connects to."
  value       = module.database.endpoint
}

output "database_secret_arn" {
  description = "Secrets Manager secret holding the assembled database URL."
  value       = module.database.secret_arn
}

output "search_endpoint" {
  description = "OpenSearch domain endpoint."
  value       = module.search.endpoint
}

output "cognito_user_pool_id" {
  description = "User pool the API verifies tokens against."
  value       = module.auth.user_pool_id
}

output "cognito_client_id" {
  description = "App client id. This is what the frontend is built with."
  value       = module.auth.client_id
}

output "cognito_issuer" {
  description = "Issuer URL an accepted token has to carry."
  value       = module.auth.issuer
}

output "cognito_hosted_ui_domain" {
  description = "Hosted UI domain the browser is sent to for sign-in."
  value       = module.auth.domain
}

output "api_service_name" {
  description = "ECS service running the API."
  value       = module.api.api_service_name
}

output "ingestion_function_name" {
  description = "Lambda function consuming the ingestion queue."
  value       = module.ingestion.function_name
}
