# Partner-facing API: Amazon API Gateway (HTTP API) -> VPC Link -> Cloud Map -> ECS API tasks.
# Used by hospitals, labs and pharmacy partners for machine-to-machine ingestion. Adds per-route
# throttling, structured access logs and an isolated hostname, separate from the interactive UI path.

resource "aws_security_group" "vpc_link" {
  name        = "${var.name}-apigw-vpclink"
  description = "API Gateway VPC link to ECS API"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_apigatewayv2_vpc_link" "this" {
  name               = "${var.name}-vpclink"
  subnet_ids         = var.private_subnet_ids
  security_group_ids = [aws_security_group.vpc_link.id]
}

resource "aws_apigatewayv2_api" "this" {
  name                         = "${var.name}-partner-api"
  protocol_type                = "HTTP"
  description                  = "SentinelHealth partner ingestion API"
  disable_execute_api_endpoint = var.custom_domain_name != ""
  cors_configuration {
    allow_origins = []
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id               = aws_apigatewayv2_api.this.id
  integration_type     = "HTTP_PROXY"
  integration_method   = "ANY"
  integration_uri      = var.cloud_map_service_arn
  connection_type      = "VPC_LINK"
  connection_id        = aws_apigatewayv2_vpc_link.this.id
  timeout_milliseconds = 29000
}

resource "aws_apigatewayv2_route" "this" {
  for_each  = toset(var.routes)
  api_id    = aws_apigatewayv2_api.this.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/sentinel/${var.name}/apigw-access"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
}

resource "aws_apigatewayv2_stage" "this" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = var.burst_limit
    throttling_rate_limit  = var.rate_limit
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId         = "$context.requestId", ip = "$context.identity.sourceIp", method = "$context.httpMethod",
      path              = "$context.path", status = "$context.status", latency = "$context.responseLatency",
      integrationStatus = "$context.integrationStatus", userAgent = "$context.identity.userAgent"
    })
  }
}

resource "aws_apigatewayv2_domain_name" "this" {
  count       = var.custom_domain_name != "" ? 1 : 0
  domain_name = var.custom_domain_name
  domain_name_configuration {
    certificate_arn = var.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
  dynamic "mutual_tls_authentication" {
    for_each = var.truststore_uri != "" ? [1] : []
    content {
      truststore_uri = var.truststore_uri # partner client certificates (mTLS)
    }
  }
}

resource "aws_apigatewayv2_api_mapping" "this" {
  count       = var.custom_domain_name != "" ? 1 : 0
  api_id      = aws_apigatewayv2_api.this.id
  domain_name = aws_apigatewayv2_domain_name.this[0].id
  stage       = aws_apigatewayv2_stage.this.id
}
