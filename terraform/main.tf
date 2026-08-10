terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    # NOTE: While HashiCorp's official providers (like 'random') can be implicitly resolved 
    # without explicit declaration, explicitly specifying them here is an enterprise best practice 
    # for strict version pinning, deterministic builds, and avoiding breaking changes in production.
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region  = "eu-central-1"
  profile = "terraform-sso-profile"
}


resource "random_pet" "bucket_suffix" {
  length    = 2
  separator = "-"
}

resource "aws_s3_bucket" "csv_bucket" {
  bucket        = "async-job-storage-${random_pet.bucket_suffix.id}"
  force_destroy = true

  tags = {
    Environment = "Dev"
    Project     = "AsyncCSVProcessor"
    ManagedBy   = "Terraform"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "job_bucket_lifecycle" {
  bucket = aws_s3_bucket.csv_bucket.id

  rule {
    id     = "delete_old_and_orphaned_csv_files"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = 1
    }
  }
}

resource "aws_sqs_queue" "job_dlq" {
  name                      = "async-job-dlq-${random_pet.bucket_suffix.id}"
  message_retention_seconds = 1209600 # 14 days

  tags = {
    Environment = "Dev"
    Project     = "AsyncCSVProcessor"
    ManagedBy   = "Terraform"
  }
}

resource "aws_sqs_queue" "job_queue" {
  name                       = "async-job-queue-${random_pet.bucket_suffix.id}"
  delay_seconds              = 0
  visibility_timeout_seconds = 300
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.job_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Environment = "Dev"
    Project     = "AsyncCSVProcessor"
    ManagedBy   = "Terraform"
  }
}

resource "aws_sns_topic" "queue_alerts" {
  name = "async-job-alerts-${random_pet.bucket_suffix.id}"

  tags = {
    Environment = "Dev"
    Project     = "AsyncCSVProcessor"
    ManagedBy   = "Terraform"
  }
}

resource "aws_sns_topic_subscription" "queue_alerts_email" {
  topic_arn = aws_sns_topic.queue_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "sqs_dlq_alarm" {
  alarm_name          = "async-job-dlq-alarm-${random_pet.bucket_suffix.id}"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "This metric monitors messages in Dead Letter Queue"

  alarm_actions = [aws_sns_topic.queue_alerts.arn]

  dimensions = {
    QueueName = aws_sqs_queue.job_dlq.name
  }

  tags = {
    Environment = "Dev"
    Project     = "AsyncCSVProcessor"
    ManagedBy   = "Terraform"
  }
}