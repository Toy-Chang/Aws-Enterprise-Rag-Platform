output "endpoint" {
  description = "Host name of the instance, without the port: the application builds its URL from the secret."
  value       = aws_db_instance.this.address
}

output "port" {
  description = "Port PostgreSQL listens on."
  value       = aws_db_instance.this.port
}

output "database_name" {
  description = "Database the application connects to."
  value       = aws_db_instance.this.db_name
}

output "secret_arn" {
  description = "Secrets Manager secret holding the assembled connection URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "instance_identifier" {
  description = "RDS instance identifier, for the console and for CLI commands."
  value       = aws_db_instance.this.identifier
}

output "instance_arn" {
  description = "ARN of the instance."
  value       = aws_db_instance.this.arn
}
