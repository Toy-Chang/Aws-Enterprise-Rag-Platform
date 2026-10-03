output "vpc_id" {
  description = "The VPC every other module places resources in."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Subnets with a route to the internet gateway. The load balancer lives here."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Subnets without a route to the internet gateway. Tasks, the consumer, the database and the search domain live here."
  value       = aws_subnet.private[*].id
}

output "alb_security_group_id" {
  description = "Security group of the load balancer."
  value       = aws_security_group.alb.id
}

output "api_security_group_id" {
  description = "Security group of the ECS tasks."
  value       = aws_security_group.api.id
}

output "database_security_group_id" {
  description = "Security group of the database. Its rules are declared in this module."
  value       = aws_security_group.database.id
}

output "search_security_group_id" {
  description = "Security group of the search domain. Its rules are declared in this module."
  value       = aws_security_group.search.id
}

output "lambda_security_group_id" {
  description = "Security group of the ingestion consumer."
  value       = aws_security_group.lambda.id
}

output "nat_gateway_public_ips" {
  description = "Public addresses anything egressing from a private subnet appears as. A partner allow-list needs these."
  value       = aws_eip.nat[*].public_ip
}
