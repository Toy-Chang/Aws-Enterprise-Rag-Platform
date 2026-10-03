output "alb_dns_name" {
  description = "Public DNS name of the load balancer. A CNAME target, and what the auth callback URL has to name in a real deployment."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "Hosted zone id of the load balancer, for an alias record."
  value       = aws_lb.this.zone_id
}

output "alb_arn" {
  description = "ARN of the load balancer."
  value       = aws_lb.this.arn
}

output "api_repository_url" {
  description = "ECR repository the API image is pushed to."
  value       = aws_ecr_repository.api.repository_url
}

output "frontend_repository_url" {
  description = "ECR repository the frontend image is pushed to."
  value       = aws_ecr_repository.frontend.repository_url
}

output "api_service_name" {
  description = "Name of the ECS service running the API."
  value       = aws_ecs_service.api.name
}

output "frontend_service_name" {
  description = "Name of the ECS service running the frontend."
  value       = aws_ecs_service.frontend.name
}

output "cluster_name" {
  description = "Name of the ECS cluster."
  value       = aws_ecs_cluster.this.name
}

output "api_log_group_name" {
  description = "CloudWatch log group of the API container."
  value       = aws_cloudwatch_log_group.api.name
}

output "frontend_log_group_name" {
  description = "CloudWatch log group of the frontend container."
  value       = aws_cloudwatch_log_group.frontend.name
}

output "api_target_group_arn" {
  description = "Target group in front of the API tasks."
  value       = aws_lb_target_group.api.arn
}
