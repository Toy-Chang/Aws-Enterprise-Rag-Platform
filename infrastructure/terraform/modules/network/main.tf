# Network foundation: a VPC with public subnets for the load balancer and private
# subnets for everything that must not be reachable from the internet.
#
# The security groups live here rather than in the modules that own the resources they
# protect, because the rules that matter are *between* concerns -- the database accepts
# traffic from the API and the consumer, and the search domain accepts traffic from the
# same two. Expressing that in one place is what makes "who can reach the database" a
# question with one answer.

locals {
  az_count = length(var.availability_zones)
  # One NAT gateway is enough for a trial and a single point of failure for egress;
  # one per zone removes that but multiplies the hourly cost.
  nat_count = var.single_nat_gateway ? 1 : local.az_count
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  count = local.az_count

  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${var.name_prefix}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count = local.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 100 + count.index)
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "${var.name_prefix}-private-${count.index + 1}" }
}

resource "aws_eip" "nat" {
  count = local.nat_count

  tags = { Name = "${var.name_prefix}-nat-${count.index + 1}" }
}

resource "aws_nat_gateway" "this" {
  count = local.nat_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = { Name = "${var.name_prefix}-nat-${count.index + 1}" }

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "${var.name_prefix}-public" }
}

resource "aws_route_table_association" "public" {
  count = local.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count = local.az_count

  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    # With a single gateway every private subnet egresses through the first one.
    nat_gateway_id = aws_nat_gateway.this[var.single_nat_gateway ? 0 : count.index].id
  }

  tags = { Name = "${var.name_prefix}-private-${count.index + 1}" }
}

resource "aws_route_table_association" "private" {
  count = local.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.name_prefix}-alb-"
  description = "Public entry point: HTTP and HTTPS from anywhere."
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTP, redirected to HTTPS when a certificate is configured"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "To the tasks behind the load balancer"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-alb" }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "api" {
  name_prefix = "${var.name_prefix}-api-"
  description = "ECS tasks running the API and the frontend."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Only the load balancer may talk to a task"
    from_port       = 0
    to_port         = 0
    protocol        = "-1"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "RDS, OpenSearch, S3, SQS, Bedrock and the Cognito key document"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-api" }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "lambda" {
  name_prefix = "${var.name_prefix}-lambda-"
  description = "The ingestion consumer. It only makes outbound calls."
  vpc_id      = aws_vpc.this.id

  egress {
    description = "SQS is reached through the interface endpoint or NAT, the rest through NAT"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-lambda" }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "database" {
  name_prefix = "${var.name_prefix}-db-"
  description = "PostgreSQL, reachable only by the API tasks and the consumer."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "The API writes documents, chunks and status"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  ingress {
    description     = "The consumer writes the outcome of an ingestion"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  egress {
    description = "Replication and the RDS control plane"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  tags = { Name = "${var.name_prefix}-database" }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "search" {
  name_prefix = "${var.name_prefix}-search-"
  description = "OpenSearch, reachable only by the API tasks and the consumer."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "HTTPS from the API"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  ingress {
    description     = "HTTPS from the consumer"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  egress {
    description = "Node-to-node traffic inside the domain"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  tags = { Name = "${var.name_prefix}-search" }

  lifecycle { create_before_destroy = true }
}
