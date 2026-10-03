output "endpoint" {
  description = "Domain endpoint without a scheme. The application prefixes https:// -- and the adapter strips it again for the SDK client, which wants a bare host."
  value       = aws_opensearch_domain.this.endpoint
}

output "domain_arn" {
  description = "ARN of the domain, for the access policy and the task policies."
  value       = aws_opensearch_domain.this.arn
}

output "domain_name" {
  description = "Name of the domain."
  value       = aws_opensearch_domain.this.domain_name
}

output "domain_id" {
  description = "Identifier of the domain."
  value       = aws_opensearch_domain.this.domain_id
}
