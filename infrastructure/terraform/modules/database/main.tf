# PostgreSQL: documents, chunks, knowledge bases and evaluation runs.
#
# The database is the source of truth for everything the API reports, which is why it gets
# Multi-AZ and backups by default and why deletion protection is on: losing it is not
# something an application can recover from by re-ingesting, because the uploaded bytes
# are addressed by rows that would be gone.

resource "aws_db_subnet_group" "this" {
  name        = "${var.name_prefix}-db"
  description = "Private subnets the database may run in"
  subnet_ids  = var.subnet_ids

  tags = { Name = "${var.name_prefix}-db" }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.database_name
  username = var.master_username
  password = var.master_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  publicly_accessible    = false

  multi_az                = var.multi_az
  backup_retention_period = var.backup_retention_days
  backup_window           = "02:00-03:00"
  maintenance_window      = "sun:03:30-sun:04:30"
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade = true
  # A change to the instance class should not take the API down without warning, so the
  # apply schedules it in the maintenance window instead of doing it immediately.
  apply_immediately = false

  # Performance Insights would need an extra IAM permission and adds cost; the metrics
  # this platform actually reports come from the application itself.
  performance_insights_enabled = false

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${var.name_prefix}-db-final" : null

  tags = { Name = "${var.name_prefix}-db" }

  lifecycle {
    # `max_allocated_storage` cannot be lower than the current size, and a plan that
    # proposes shrinking it would be rejected by AWS half way through an apply.
    precondition {
      condition     = var.max_allocated_storage_gb >= var.allocated_storage_gb
      error_message = "max_allocated_storage_gb has to be at least allocated_storage_gb."
    }
  }
}

# The application consumes one assembled SQLAlchemy URL, so the secret carries the URL as
# well as the parts: a deployment that needs the host and the password separately (a
# migration job, for instance) can read them without re-assembling anything.
resource "aws_secretsmanager_secret" "database_url" {
  name        = "${var.name_prefix}-database-url"
  description = "Connection URL for the ${var.name_prefix} PostgreSQL instance"

  # Destroying this secret and recreating it within the recovery window would otherwise
  # fail; the database itself is the resource that must not be lost.
  recovery_window_in_days = 7

  tags = { Name = "${var.name_prefix}-database-url" }
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id

  secret_string = jsonencode({
    username = var.master_username
    password = var.master_password
    host     = aws_db_instance.this.address
    port     = aws_db_instance.this.port
    dbname   = var.database_name
    # The password is percent-encoded: a password containing `@`, `/` or `:` would
    # otherwise produce a URL that does not parse, and the failure would appear at the
    # first request rather than here.
    url = "postgresql+psycopg://${var.master_username}:${urlencode(var.master_password)}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${var.database_name}"
  })
}
