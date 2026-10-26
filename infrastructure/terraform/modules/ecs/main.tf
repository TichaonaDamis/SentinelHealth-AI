# ECS on Fargate: API (FastAPI) and web (Next.js) services, plus a one-off migration task.
#
# Traffic:
#   users    -> WAF -> public ALB (HTTPS) -> web  and  /api/* -> api
#   partners -> API Gateway (HTTP API, throttled) -> VPC Link -> Cloud Map -> api   (see api_gateway module)

data "aws_region" "current" {}

locals {
  services = {
    api = { port = 8000, cpu = var.api_cpu, memory = var.api_memory, health = "/health", min = var.api_min_tasks, max = var.api_max_tasks }
    web = { port = 3000, cpu = 512, memory = 1024, health = "/", min = var.web_min_tasks, max = var.web_max_tasks }
  }
  secret_names = ["jwt-secret", "field-encryption-key", "database-url", "anthropic-api-key", "openai-api-key"]
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
  configuration {
    execute_command_configuration {
      kms_key_id = var.logs_kms_key_arn
      logging    = "OVERRIDE"
      log_configuration {
        cloud_watch_encryption_enabled = true
        cloud_watch_log_group_name     = aws_cloudwatch_log_group.exec.name
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "exec" {
  name              = "/sentinel/${var.name}/ecs-exec"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
}

resource "aws_cloudwatch_log_group" "service" {
  for_each          = merge(local.services, { migrate = null })
  name              = "/sentinel/${var.name}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
}

resource "aws_ecr_repository" "this" {
  for_each             = toset(["api", "web", "airflow"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.data_kms_key_arn
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 50 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 50 }
      action       = { type = "expire" }
    }]
  })
}

# --- secrets (values are set out-of-band; never in Terraform state) ---------------
resource "aws_secretsmanager_secret" "app" {
  for_each   = toset(local.secret_names)
  name       = "sentinel/${var.name}/${each.key}"
  kms_key_id = var.secrets_kms_key_arn
}

# --- IAM ---------------------------------------------------------------------------
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [for s in aws_secretsmanager_secret.app : s.arn] },
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = [var.secrets_kms_key_arn, var.data_kms_key_arn] },
    ]
  })
}

resource "aws_iam_role" "api_task" {
  name               = "${var.name}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "api_task" {
  role = aws_iam_role.api_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "ModelRegistryRead", Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"], Resource = [var.models_bucket_arn, "${var.models_bucket_arn}/*"] },
      { Sid = "Notify", Effect = "Allow", Action = ["sns:Publish"], Resource = [var.alerts_topic_arn] },
      { Sid = "Email", Effect = "Allow", Action = ["ses:SendEmail"], Resource = "*", Condition = { StringEquals = { "ses:FromAddress" = var.ses_sender } } },
      { Sid = "DistributionLists", Effect = "Allow", Action = ["ssm:GetParameter"], Resource = "arn:aws:ssm:${data.aws_region.current.name}:*:parameter/sentinel/distribution/*" },
      { Sid = "OpenSearch", Effect = "Allow", Action = ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut"], Resource = "${var.opensearch_domain_arn}/*" },
      { Sid = "Kms", Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = [var.data_kms_key_arn] },
      { Sid = "EcsExec", Effect = "Allow", Action = ["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"], Resource = "*" },
    ]
  })
}

resource "aws_iam_role" "web_task" {
  name               = "${var.name}-web-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# --- networking ------------------------------------------------------------------
resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "Public HTTPS"
  vpc_id      = var.vpc_id
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTP (redirected to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_security_group" "service" {
  for_each    = local.services
  name        = "${var.name}-${each.key}"
  description = "${each.key} tasks"
  vpc_id      = var.vpc_id
  ingress {
    description     = "From ALB"
    from_port       = each.value.port
    to_port         = each.value.port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  ingress {
    description = "From inside VPC (API Gateway VPC link, Airflow)"
    from_port   = each.value.port
    to_port     = each.value.port
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "this" {
  name                       = "${var.name}-alb"
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = var.deletion_protection
  access_logs {
    bucket  = var.alb_logs_bucket
    prefix  = "alb"
    enabled = var.alb_logs_bucket != ""
  }
}

resource "aws_lb_target_group" "this" {
  for_each    = local.services
  name        = "${var.name}-${each.key}"
  port        = each.value.port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id
  health_check {
    path                = each.value.health
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    matcher             = "200-399"
  }
  deregistration_delay = 30
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["web"].arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["api"].arn
  }
  condition {
    path_pattern {
      values = ["/api/*", "/health", "/ready"]
    }
  }
}

# --- WAF ---------------------------------------------------------------------------
resource "aws_wafv2_web_acl" "this" {
  name  = "${var.name}-waf"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  dynamic "rule" {
    for_each = { AWSManagedRulesCommonRuleSet = 1, AWSManagedRulesKnownBadInputsRuleSet = 2, AWSManagedRulesSQLiRuleSet = 3, AWSManagedRulesAmazonIpReputationList = 4 }
    content {
      name     = rule.key
      priority = rule.value
      override_action {
        none {}
      }
      statement {
        managed_rule_group_statement {
          name        = rule.key
          vendor_name = "AWS"
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.key
        sampled_requests_enabled   = true
      }
    }
  }
  rule {
    name     = "rate-limit"
    priority = 10
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name}-waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.this.arn
  web_acl_arn  = aws_wafv2_web_acl.this.arn
}

# --- service discovery (for API Gateway VPC link) ----------------------------------
resource "aws_service_discovery_private_dns_namespace" "this" {
  name = "${var.name}.internal"
  vpc  = var.vpc_id
}

resource "aws_service_discovery_service" "api" {
  name = "api"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id
    dns_records {
      ttl  = 10
      type = "SRV"
    }
    routing_policy = "MULTIVALUE"
  }
  health_check_custom_config {
    failure_threshold = 1
  }
}

# --- task definitions --------------------------------------------------------------
locals {
  api_environment = [
    { name = "SENTINEL_ENVIRONMENT", value = var.environment },
    { name = "SENTINEL_CORS_ORIGINS", value = jsonencode(["https://${var.domain_name}"]) },
    { name = "SENTINEL_TRUSTED_HOSTS", value = jsonencode([var.domain_name, "api.${aws_service_discovery_private_dns_namespace.this.name}", "*.amazonaws.com", "localhost"]) },
    { name = "SENTINEL_MODEL_DIR", value = "/tmp/models" }, # synced from S3 at start-up (read-only root fs)
    { name = "SENTINEL_MODEL_S3_URI", value = "s3://${var.models_bucket_name}/champion/" },
    { name = "SENTINEL_NOTIFICATION_CHANNELS", value = jsonencode(["in_app", "log", "email", "sms", "webhook"]) },
    { name = "SENTINEL_SNS_TOPIC_ARN", value = var.alerts_topic_arn },
    { name = "SENTINEL_SES_SENDER", value = var.ses_sender },
    { name = "SENTINEL_OPENSEARCH_URL", value = "https://${var.opensearch_endpoint}" },
    { name = "SENTINEL_COPILOT_PROVIDER", value = "anthropic" },
  ]
  api_secrets = [
    { name = "SENTINEL_JWT_SECRET", valueFrom = aws_secretsmanager_secret.app["jwt-secret"].arn },
    { name = "SENTINEL_FIELD_ENCRYPTION_KEY", valueFrom = aws_secretsmanager_secret.app["field-encryption-key"].arn },
    { name = "SENTINEL_DATABASE_URL", valueFrom = aws_secretsmanager_secret.app["database-url"].arn },
    { name = "SENTINEL_ANTHROPIC_API_KEY", valueFrom = aws_secretsmanager_secret.app["anthropic-api-key"].arn },
    { name = "SENTINEL_OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.app["openai-api-key"].arn },
  ]
  container_defaults = {
    essential              = true
    readonlyRootFilesystem = true
    user                   = "10001"
    linuxParameters        = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.services.api.cpu
  memory                   = local.services.api.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  volume {
    name = "tmp"
  }
  container_definitions = jsonencode([merge(local.container_defaults, {
    name         = "api"
    image        = "${aws_ecr_repository.this["api"].repository_url}:${var.image_tag}"
    portMappings = [{ containerPort = 8000, protocol = "tcp", name = "http" }]
    environment  = local.api_environment
    secrets      = local.api_secrets
    mountPoints  = [{ sourceVolume = "tmp", containerPath = "/tmp" }]
    healthCheck  = { command = ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8000/health')\""], interval = 15, timeout = 5, retries = 3, startPeriod = 30 }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["api"].name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "api"
      }
    }
  })])
}

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  container_definitions = jsonencode([{
    name        = "migrate"
    image       = "${aws_ecr_repository.this["api"].repository_url}:${var.image_tag}"
    essential   = true
    command     = ["alembic", "upgrade", "head"]
    environment = local.api_environment
    secrets     = local.api_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["migrate"].name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "migrate"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${var.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.services.web.cpu
  memory                   = local.services.web.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.web_task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  container_definitions = jsonencode([merge(local.container_defaults, {
    name                   = "web"
    image                  = "${aws_ecr_repository.this["web"].repository_url}:${var.image_tag}"
    portMappings           = [{ containerPort = 3000, protocol = "tcp" }]
    readonlyRootFilesystem = false # Next.js writes its cache under .next/cache
    environment = [
      { name = "API_INTERNAL_URL", value = "https://${var.domain_name}" }, # BFF -> API through ALB + WAF
      { name = "NEXT_PUBLIC_MAPBOX_TOKEN", value = var.mapbox_public_token },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["web"].name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "web"
      }
    }
  })])
}

resource "aws_ecs_service" "this" {
  for_each                          = local.services
  name                              = each.key
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = each.key == "api" ? aws_ecs_task_definition.api.arn : aws_ecs_task_definition.web.arn
  desired_count                     = each.value.min
  launch_type                       = "FARGATE"
  enable_execute_command            = var.environment != "prod"
  health_check_grace_period_seconds = 60
  propagate_tags                    = "SERVICE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service[each.key].id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.this[each.key].arn
    container_name   = each.key
    container_port   = each.value.port
  }
  dynamic "service_registries" {
    for_each = each.key == "api" ? [1] : []
    content {
      registry_arn = aws_service_discovery_service.api.arn
      port         = each.value.port
    }
  }
  lifecycle {
    ignore_changes = [desired_count] # managed by autoscaling
  }
  depends_on = [aws_lb_listener.https]
}

resource "aws_appautoscaling_target" "this" {
  for_each           = local.services
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.this[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = each.value.min
  max_capacity       = each.value.max
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each           = local.services
  name               = "${each.key}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.this[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.this[each.key].scalable_dimension
  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
