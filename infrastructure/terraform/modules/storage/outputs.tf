output "bucket_name" {
  description = "Name of the document bucket. The API is configured with it."
  value       = aws_s3_bucket.documents.id
}

output "bucket_arn" {
  description = "ARN of the document bucket, for the task and consumer policies."
  value       = aws_s3_bucket.documents.arn
}

output "bucket_regional_domain_name" {
  description = "Regional endpoint of the bucket."
  value       = aws_s3_bucket.documents.bucket_regional_domain_name
}
