output "api_task_role_arn" {
  description = "Role the API container runs as, which is what the ECS task definition sets as its task role."
  value       = aws_iam_role.api_task.arn
}

output "api_task_role_name" {
  description = "Name of the API task role, for policies that need to name the principal."
  value       = aws_iam_role.api_task.name
}

output "api_execution_role_arn" {
  description = "Role the ECS agent assumes for the API task: image pull, logs and secret resolution."
  value       = aws_iam_role.api_execution.arn
}

output "api_execution_role_name" {
  description = "Name of the API execution role."
  value       = aws_iam_role.api_execution.name
}

output "ingestion_role_arn" {
  description = "Role the ingestion Lambda runs as, which is what the function's own resource needs."
  value       = aws_iam_role.ingestion.arn
}

output "ingestion_role_name" {
  description = "Name of the ingestion role."
  value       = aws_iam_role.ingestion.name
}
