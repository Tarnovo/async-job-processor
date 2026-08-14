output "s3_bucket_name" {
  description = "The name of the S3 bucket created for storing CSV files."
  value       = aws_s3_bucket.csv_bucket.id
}

output "sqs_queue_url" {
  description = "The URL of the SQS queue created for processing jobs."
  value       = aws_sqs_queue.job_queue.id
}

output "sqs_dlq_url" {
  description = "The URL of the DLQ created for handling failed job messages."
  value       = aws_sqs_queue.job_dlq.id
}

output "github_actions_role_arn" {
  description = "The ARN of the IAM role created for GitHub Actions OIDC to assume."
  value       = aws_iam_role.github_actions_role.arn
}

output "cloudfront_domain_name" {
  description = "The domain name of the CloudFront distribution for the frontend"
  value       = aws_cloudfront_distribution.frontend_cdn.domain_name
}

output "cloudfront_distribution_id" {
  description = "The ID of the CloudFront distribution for cache invalidations"
  value       = aws_cloudfront_distribution.frontend_cdn.id
}

output "frontend_bucket_name" {
  description = "The name of the S3 bucket created for hosting the frontend static assets."
  value       = aws_s3_bucket.frontend_bucket.id
}