# The document bucket.
#
# `bucket_prefix` rather than `bucket`: S3 names are globally unique, and a fixed name
# would make a second deployment in another account fail for a reason that has nothing to
# do with the deployment. AWS appends a suffix.

resource "aws_s3_bucket" "documents" {
  bucket_prefix = "${var.name_prefix}-documents-"
  force_destroy = var.force_destroy

  tags = { Name = "${var.name_prefix}-documents" }
}

# Nothing in this platform reads a bucket over the public internet. Blocking all four
# forms is what makes that a property of the bucket rather than of every caller.
resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    # A re-upload of the same document overwrites an object, and an ingestion bug that
    # corrupts one is recoverable only if the previous version still exists.
    status = "Enabled"
  }
}

# SSE-KMS with the AWS-managed `aws/s3` key: authenticated encryption and an audit trail
# through CloudTrail, without a key policy to maintain or an extra grant for the task and
# consumer roles. A customer-managed key is the next step -- it adds key rotation under
# your control and the ability to revoke access by disabling the key -- and it is not
# free of wiring.
resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = "aws/s3"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Refuse anything that is not TLS, including a request signed with valid credentials.
# Encryption at rest and encryption in transit are separate properties, and this is the
# second one.
data "aws_iam_policy_document" "documents" {
  statement {
    sid     = "DenyUnencryptedTransport"
    effect  = "Deny"
    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.documents.arn,
      "${aws_s3_bucket.documents.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = data.aws_iam_policy_document.documents.json
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  # An upload that dies halfway leaves parts that are billed but never readable.
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-superseded-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.expire_noncurrent_versions_days
    }
  }
}
