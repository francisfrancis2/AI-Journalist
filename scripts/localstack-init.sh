#!/bin/bash
# LocalStack initialisation script — creates S3 buckets on startup.

set -e

echo "LocalStack: creating S3 buckets..."

aws --endpoint-url=http://localhost:4566 s3 mb s3://ai-journalist-scripts --region us-east-1 || true
aws --endpoint-url=http://localhost:4566 s3 mb s3://ai-journalist-assets --region us-east-1 || true

echo "LocalStack: S3 buckets ready."
