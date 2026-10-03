# The vector index.
#
# The application writes chunk text plus a k-NN vector into this domain and searches it by
# cosine similarity. `min_score` in the API is a cosine threshold, and the adapter
# converts OpenSearch's `(1 + cosine) / 2` scores back to the cosine scale, so the index
# mapping and the application's notion of similarity have to agree.

data "aws_iam_policy_document" "access" {
  statement {
    sid    = "DomainAccess"
    effect = "Allow"

    actions = ["es:ESHttp*"]

    resources = [
      "arn:aws:es:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:domain/${var.domain_name}",
      "arn:aws:es:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:domain/${var.domain_name}/*",
    ]

    principals {
      type        = "AWS"
      identifiers = var.allowed_principal_arns
    }
  }
}

data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "search" {
  count = var.enable_audit_logs ? 1 : 0

  name              = "/aws/opensearch/${var.domain_name}"
  retention_in_days = var.log_retention_days

  tags = { Name = "${var.name_prefix}-search-logs" }
}

# The log resource policy is a per-account singleton: it may be declared once per account,
# and applying a second one from another stack would fight over it. That is the reason
# audit logging is opt-in here rather than on by default.
resource "aws_cloudwatch_log_resource_policy" "search" {
  count = var.enable_audit_logs ? 1 : 0

  policy_name = "${var.name_prefix}-opensearch-logs"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "es.amazonaws.com" }
      Action    = ["logs:PutLogEvents", "logs:CreateLogStream"]
      Resource  = "${aws_cloudwatch_log_group.search[0].arn}:*"
    }]
  })
}

resource "aws_opensearch_domain" "this" {
  domain_name    = var.domain_name
  engine_version = var.engine_version

  cluster_config {
    instance_type = var.instance_type

    # Zone awareness needs an even number of nodes and at least two; declaring the
    # precondition below keeps a one-node "highly available" domain from being planned.
    instance_count         = var.zone_awareness_enabled ? max(2, var.instance_count) : var.instance_count
    zone_awareness_enabled = var.zone_awareness_enabled

    dynamic "zone_awareness_config" {
      for_each = var.zone_awareness_enabled ? [1] : []
      content {
        availability_zone_count = 2
      }
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.volume_size_gb
  }

  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  # Access is IAM-based: the task role and the consumer role are the only principals in
  # the policy, and both reach the domain through its HTTPS endpoint inside the VPC.
  # Fine-grained access control (an internal user database, per-index roles) would need
  # `advanced_security_options` with a master user, which is a different operational
  # model; the application supports OpenSearch Serverless too, where that is mandatory.
  advanced_security_options {
    enabled = false
  }

  access_policies = data.aws_iam_policy_document.access.json

  dynamic "log_publishing_options" {
    for_each = var.enable_audit_logs ? ["ES_APPLICATION_LOGS", "AUDIT_LOGS"] : []
    content {
      log_type                 = log_publishing_options.value
      cloudwatch_log_group_arn = aws_cloudwatch_log_group.search[0].arn
    }
  }

  tags = { Name = var.domain_name }

  # The domain must be able to write before the policy allows it to, and a meta-argument
  # cannot live inside a dynamic block's content, so the ordering is declared here.
  depends_on = [aws_cloudwatch_log_resource_policy.search]
}
