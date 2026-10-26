# Amazon RDS for PostgreSQL 16 with PostGIS + pgvector (installed by migrations).
# Note: RDS does not offer the TimescaleDB extension. Migrations detect this and fall back to
# BRIN-indexed tables + materialized views; set `external_timescale_url` in the environment to
# use Timescale Cloud (VPC-peered) instead when hypertable compression/continuous aggregates are required.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "PostgreSQL access from application tier only"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-db" }
}

resource "aws_vpc_security_group_ingress_rule" "db" {
  for_each                     = toset(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = each.value
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "PostgreSQL from app tier"
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl" # encryption in transit is mandatory
    value = "1"
  }
  parameter {
    name  = "ssl_min_protocol_version"
    value = "TLSv1.2"
  }
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements,pgaudit"
    apply_method = "pending-reboot"
  }
  parameter {
    name  = "pgaudit.log" # database-level audit of DDL and role changes
    value = "ddl,role"
  }
  parameter {
    name  = "log_connections"
    value = "1"
  }
  parameter {
    name  = "log_disconnections"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "2000"
  }
}

resource "aws_iam_role" "monitoring" {
  name = "${var.name}-rds-monitoring"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "monitoring.rds.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "monitoring" {
  role       = aws_iam_role.monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_db_instance" "this" {
  identifier                            = "${var.name}-postgres"
  engine                                = "postgres"
  engine_version                        = var.engine_version
  instance_class                        = var.instance_class
  allocated_storage                     = var.allocated_storage_gb
  max_allocated_storage                 = var.max_allocated_storage_gb
  storage_type                          = "gp3"
  storage_encrypted                     = true
  kms_key_id                            = var.kms_key_arn
  db_name                               = "sentinel"
  username                              = "sentinel_admin"
  manage_master_user_password           = true # rotated by Secrets Manager
  master_user_secret_kms_key_id         = var.secrets_kms_key_arn
  iam_database_authentication_enabled   = true
  multi_az                              = var.multi_az
  db_subnet_group_name                  = aws_db_subnet_group.this.name
  vpc_security_group_ids                = [aws_security_group.db.id]
  parameter_group_name                  = aws_db_parameter_group.this.name
  publicly_accessible                   = false
  backup_retention_period               = var.backup_retention_days
  backup_window                         = "03:00-04:00"
  maintenance_window                    = "sun:04:30-sun:05:30"
  copy_tags_to_snapshot                 = true
  deletion_protection                   = var.deletion_protection
  skip_final_snapshot                   = !var.deletion_protection
  final_snapshot_identifier             = var.deletion_protection ? "${var.name}-final" : null
  performance_insights_enabled          = true
  performance_insights_kms_key_id       = var.kms_key_arn
  performance_insights_retention_period = 7
  monitoring_interval                   = 30
  monitoring_role_arn                   = aws_iam_role.monitoring.arn
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]
  auto_minor_version_upgrade            = true
}

resource "aws_db_instance" "replica" {
  count                        = var.read_replica_count
  identifier                   = "${var.name}-postgres-replica-${count.index}"
  replicate_source_db          = aws_db_instance.this.identifier
  instance_class               = var.instance_class
  storage_encrypted            = true
  kms_key_id                   = var.kms_key_arn
  vpc_security_group_ids       = [aws_security_group.db.id]
  parameter_group_name         = aws_db_parameter_group.this.name
  publicly_accessible          = false
  performance_insights_enabled = true
  skip_final_snapshot          = true
}
