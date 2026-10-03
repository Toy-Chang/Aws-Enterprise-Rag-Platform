output "function_name" {
  description = "Name of the Lambda function."
  value       = aws_lambda_function.ingestion.function_name
}

output "function_arn" {
  description = "ARN of the Lambda function."
  value       = aws_lambda_function.ingestion.arn
}

output "role_arn" {
  description = "Role the function runs as, passed through for callers that want to inspect it."
  value       = var.role_arn
}

output "repository_url" {
  description = "ECR repository the ingestion image is pushed to."
  value       = aws_ecr_repository.ingestion.repository_url
}

output "log_group_name" {
  description = "CloudWatch log group of the function."
  value       = aws_cloudwatch_log_group.ingestion.name
}

output "event_source_mapping_id" {
  description = "Identifier of the mapping between the queue and the function."
  value       = aws_lambda_event_source_mapping.ingestion.uuid
}
