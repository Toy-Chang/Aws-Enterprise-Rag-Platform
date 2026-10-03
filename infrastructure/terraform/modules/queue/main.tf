# The ingestion queue and the dead-letter queue behind it.
#
# The API publishes one message per document and never consumes: ingestion happens in the
# Lambda the main stack wires to this queue. A message carries only identifiers, so losing
# one is recoverable by re-queueing the document -- but a message that no delivery could
# process is a document that never becomes searchable, which is why the DLQ is alarmed.

locals {
  # The root stack's provider applies Project/Environment/ManagedBy to everything; only
  # the per-resource name is worth repeating here, and each queue carries its own.
  tags = {
    Name = "${var.name_prefix}-ingestion"
  }
}

# The dead-letter queue keeps messages for the longest time SQS allows. `maxReceiveCount`
# stops the retry loop, and there is no automatic way back: a message here is read by hand
# or by a replay tool during an investigation, so it has to outlive the incident. A message
# body is a few hundred bytes, so keeping every failure for two weeks costs nothing.
resource "aws_sqs_queue" "dead_letter" {
  name                       = "${var.name_prefix}-ingestion-dlq"
  message_retention_seconds  = 1209600
  sqs_managed_sse_enabled    = true
  visibility_timeout_seconds = var.visibility_timeout_seconds

  tags = local.tags
}

# The queue the API sends to. Server-side encryption is on unconditionally: the message
# names a knowledge base and a document but the identifiers are still account data, and
# SSE-SQS costs nothing and needs no key policy for callers to get wrong.
resource "aws_sqs_queue" "ingestion" {
  name                       = "${var.name_prefix}-ingestion"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  sqs_managed_sse_enabled    = true

  # Long polling. The Lambda event source mapping polls on its own and is unaffected, but
  # any other consumer pays for one request per empty receive instead of per message.
  receive_wait_time_seconds = 20

  # After this many deliveries the message is moved rather than handed out again: the
  # document is malformed or the dependencies are down, and both need a person. The count
  # is compared with the *receive* count, so a redelivery after a visibility timeout
  # counts as one of them.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = local.tags
}

# Fires on the first message that reached the DLQ. One is already a failure the stack
# cannot clear by itself, so the threshold is not "a few to avoid noise" -- everything in
# this queue deserves a look.
resource "aws_cloudwatch_metric_alarm" "dead_letter_not_empty" {
  alarm_name        = "${var.name_prefix}-ingestion-dlq-not-empty"
  alarm_description = "An ingestion message failed every delivery and is sitting in ${aws_sqs_queue.dead_letter.name}; the document it names is not searchable."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.dead_letter.name
  }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  # An empty DLQ publishes no datapoint at all, and "no data" here means "nothing failed".
  # Without this the alarm would flap to INSUFFICIENT_DATA and page nobody usefully.
  treat_missing_data = "notBreaching"

  # The topic lives in the root module, so it is optional: with no ARN the alarm still
  # exists, records its state and is visible on the dashboard -- it just notifies nobody.
  alarm_actions = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
  ok_actions    = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]

  tags = local.tags
}
