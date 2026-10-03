# The ingestion consumer.
#
# One document per message. The API publishes after it has committed the row, the function
# downloads the object, extracts, chunks, embeds and writes, and only a document in a
# terminal state causes its message to be deleted. Anything else stays on the queue and is
# retried, and the queue's own redrive policy -- not a Lambda setting -- decides when a
# message has been delivered for the last time.

locals {
  # The alarm dimensions want the queue name, and the queue module hands out its URL.
  queue_name = regex("[^/]+$", var.queue_url)

  alarm_actions = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
}

resource "aws_ecr_repository" "ingestion" {
  name                 = "${var.name_prefix}-ingestion"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "${var.name_prefix}-ingestion" }
}

resource "aws_ecr_lifecycle_policy" "ingestion" {
  repository = aws_ecr_repository.ingestion.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the ten most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "ingestion" {
  name              = "/aws/lambda/${var.name_prefix}-ingestion"
  retention_in_days = var.log_retention_days

  tags = { Name = "${var.name_prefix}-ingestion-logs" }
}

resource "aws_lambda_function" "ingestion" {
  function_name = "${var.name_prefix}-ingestion"
  role          = var.role_arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.ingestion.repository_url}:${var.image_tag}"
  memory_size   = var.memory_mb
  timeout       = var.timeout_seconds

  # The same image serves the API, so the handler has to be named here: without it the
  # container's own CMD would start the web server inside a Lambda invocation.
  image_config {
    command = [var.handler]
  }

  # Has to match the architecture the image was built for. An Apple silicon machine builds
  # arm64 by default.
  architectures = [var.cpu_architecture]

  # A Lambda cannot resolve an environment variable from Secrets Manager the way an ECS
  # task definition can. The database URL is therefore not configured here: the function
  # receives APP_DATABASE_SECRET_ARN and reads the assembled URL out of the secret through
  # its role at cold start, so the password never reaches a function configuration that
  # anyone with lambda:GetFunctionConfiguration can read.
  environment {
    variables = var.environment
  }

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  # AWS keeps a version per publish; nothing here addresses a version, and a version per
  # deploy would accumulate without a consumer.
  publish = false

  # Unreserved concurrency: the queue is the backpressure, and a reserved pool would idle.
  reserved_concurrent_executions = -1

  # X-Ray stays off because Active tracing needs the xray:Put* actions on the role, and
  # this stack's roles do not grant them. Turning it on is a role change, not just a flag.
  tracing_config {
    mode = "PassThrough"
  }

  tags = { Name = "${var.name_prefix}-ingestion" }

  depends_on = [aws_cloudwatch_log_group.ingestion]
}

resource "aws_lambda_event_source_mapping" "ingestion" {
  event_source_arn = var.queue_arn
  function_name    = aws_lambda_function.ingestion.arn
  batch_size       = var.batch_size

  # Zero means "as soon as one message is there"; a batching window would add latency to a
  # pipeline a person is waiting on.
  maximum_batching_window_in_seconds = var.maximum_batching_window_seconds

  # MANDATORY. The handler answers with `batchItemFailures`, and this is what tells the
  # event source mapping to retry exactly those messages. Without it, a batch that failed
  # halfway has every message deleted, and the documents that were never ingested stay
  # `pending` forever with nothing left to retry.
  function_response_types = ["ReportBatchItemFailures"]

  # A batch that fails as a whole is split in two, so one poison document cannot keep
  # failing alongside four healthy ones.
  bisect_batch_on_function_error = true

  # No maximum_retry_attempts: leaving it unset keeps the queue's redrive policy
  # (maxReceiveCount on the queue, declared in the queue module) as the single authority
  # on when a message has had its last delivery. A finite value here would silently drop
  # records that the dead-letter queue should have received.
}

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${var.name_prefix}-ingestion-errors"
  alarm_description   = "An invocation failed: at least one document could not be ingested."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.ingestion.function_name
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = { Name = "${var.name_prefix}-ingestion-errors" }
}

resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "${var.name_prefix}-ingestion-throttles"
  alarm_description   = "The consumer was throttled: ingestion is slowing down."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.ingestion.function_name
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = { Name = "${var.name_prefix}-ingestion-throttles" }
}

# The queue's own age metric, not the function's: a document that has been waiting longer
# than ten minutes is a user-visible problem whether or not anything errored.
resource "aws_cloudwatch_metric_alarm" "oldest_message" {
  alarm_name          = "${var.name_prefix}-ingestion-backlog"
  alarm_description   = "A document has been waiting on the queue for over ten minutes."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 600
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = local.queue_name
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = { Name = "${var.name_prefix}-ingestion-backlog" }
}
