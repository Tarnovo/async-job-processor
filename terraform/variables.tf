variable "alert_email" {
  description = "Email address to send alerts to"
  type        = string
}

variable "project_name" {
  description = "Name of the project"
  type        = string
}

variable "region" {
  description = "AWS region to deploy resources in"
  type        = string
}

variable "db_username" {
  description = "Username for the RDS database"
  type        = string
  sensitive   = true
}

variable "github_repo" {
  description = "GitHub repository URL for the project"
  type        = string
}