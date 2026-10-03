output "queue_url" {
  description = "URL the API publishes ingestion work to."
  value       = aws_sqs_queue.ingestion.url
}

output "queue_arn" {
  description = "ARN of the ingestion queue, for IAM policies and the event source mapping."
  value       = aws_sqs_queue.ingestion.arn
}

output "queue_name" {
  description = "Name of the ingestion queue, which is what CloudWatch dimensions and the AWS CLI take."
  value       = aws_sqs_queue.ingestion.name
}

output "dead_letter_queue_url" {
  description = "URL of the queue holding messages no delivery could process."
  value       = aws_sqs_queue.dead_letter.url
}

output "dead_letter_queue_arn" {
  description = "ARN of the dead-letter queue, used as the event source mapping's failure destination."
  value       = aws_sqs_queue.dead_letter.arn
}

output "dead_letter_queue_name" {
  description = "Name of the dead-letter queue."
  value       = aws_sqs_queue.dead_letter.name
}
