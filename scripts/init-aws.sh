#!/bin/bash
# LocalStack Initialization Script

echo "Initializing LocalStack Resources..."

# S3 Bucket oluşturuluyor
awslocal s3 mb s3://csv-upload-bucket
echo "S3 Bucket (csv-upload-bucket) created."

# SQS Queue oluşturuluyor
awslocal sqs create-queue --queue-name job-processing-queue
echo "SQS Queue (job-processing-queue) created."

echo "Initialization Complete."