# twrh AWS 基礎建設（aws-deployment-plan A2）：
# ECR + ECS Fargate + EFS + CloudWatch Logs + EventBridge Scheduler。
# 沒有常駐主機、沒有 NAT Gateway——task 走 default VPC 的 public subnet 直接出網。

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
  default_tags {
    tags = { project = "twrh" }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ---- ECR ----
resource "aws_ecr_repository" "crawler" {
  name                 = "twrh-crawler"
  image_tag_mutability = "MUTABLE"
}

resource "aws_ecr_repository" "publisher" {
  name                 = "twrh-publisher"
  image_tag_mutability = "MUTABLE"
}

resource "aws_ecr_lifecycle_policy" "keep_recent" {
  for_each   = { crawler = aws_ecr_repository.crawler.name, publisher = aws_ecr_repository.publisher.name }
  repository = each.value
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

# ---- Logs ----
resource "aws_cloudwatch_log_group" "crawler" {
  name              = "/twrh/crawler"
  retention_in_days = 90
}

# ---- EFS：logs/、datas/、progress/ 的家 ----
resource "aws_efs_file_system" "shared" {
  encrypted = true
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  tags = { Name = "twrh-shared" }
}

resource "aws_security_group" "task" {
  name_prefix = "twrh-task-"
  vpc_id      = data.aws_vpc.default.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "efs" {
  name_prefix = "twrh-efs-"
  vpc_id      = data.aws_vpc.default.id
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }
}

resource "aws_efs_mount_target" "shared" {
  for_each        = toset(data.aws_subnets.default.ids)
  file_system_id  = aws_efs_file_system.shared.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

# ---- SSM 機密佔位（value 人工填，terraform 不管內容）----
resource "aws_ssm_parameter" "secrets" {
  for_each = toset(["db-password", "slack-webhook", "sentry-dsn"])
  name     = "/twrh/${each.value}"
  type     = "SecureString"
  value    = "CHANGEME"
  lifecycle {
    ignore_changes = [value]
  }
}

# ---- ECS ----
resource "aws_ecs_cluster" "twrh" {
  name = "twrh"
}

locals {
  effective_db_host = var.db_host != "" ? var.db_host : (var.enable_rds ? aws_db_instance.twrh[0].address : "")
  crawler_env = [
    { name = "TWRH_DB_NAME", value = var.db_name },
    { name = "TWRH_DB_USER", value = var.db_user },
    { name = "TWRH_DB_HOST", value = local.effective_db_host },
    # container 預設 UTC，TWRH_TARGET_DATE 會算錯天（2026-08-29 本機實踩）
    { name = "TZ", value = "Asia/Taipei" },
    # 禮貌/效能參數 per-env 設定（terraform.tfvars，不入版控）；repo 內預設不變
    { name = "TWRH_ROBOTSTXT_OBEY", value = var.robotstxt_obey },
    { name = "TWRH_AUTOTHROTTLE", value = var.autothrottle },
    { name = "TWRH_DOWNLOAD_DELAY", value = var.crawl_download_delay },
    { name = "TWRH_CONCURRENT_REQUESTS", value = var.crawl_concurrency },
    { name = "DETAIL_BATCH_SIZE", value = "10000" },
    # housekeep.sh（raw offload / HouseTS 歸檔）上傳目標
    { name = "TWRH_RAW_BUCKET", value = aws_s3_bucket.raw.bucket },
    # orchestrate.sh（模型 A）開/查 detail worker 所需
    { name = "AWS_DEFAULT_REGION", value = var.region },
    { name = "TWRH_CLUSTER", value = aws_ecs_cluster.twrh.name },
    { name = "TWRH_TASK_DEF", value = "twrh-crawler" },
    { name = "TWRH_SUBNETS", value = join(",", data.aws_subnets.default.ids) },
    { name = "TWRH_TASK_SG", value = aws_security_group.task.id },
    { name = "TWRH_DETAIL_WORKERS", value = tostring(var.detail_workers) },
    { name = "TWRH_WORKER_CPU", value = tostring(var.worker_cpu) },
    { name = "TWRH_WORKER_MEMORY", value = tostring(var.worker_memory) },
    { name = "TWRH_WORKER_CONCURRENCY", value = var.worker_concurrency },
    { name = "TWRH_WORKER_DELAY", value = var.worker_download_delay },
  ]
  crawler_secrets = [
    { name = "TWRH_DB_PASSWORD", valueFrom = aws_ssm_parameter.secrets["db-password"].arn },
    { name = "SLACK_WEBHOOK_URL", valueFrom = aws_ssm_parameter.secrets["slack-webhook"].arn },
    { name = "SENTRY_DSN", valueFrom = aws_ssm_parameter.secrets["sentry-dsn"].arn },
  ]
  # EFS 掛到 /data，容器內以 symlink/工作目錄約定對應 ../logs 與 datas/
  mount_points = [
    { sourceVolume = "shared", containerPath = "/data", readOnly = false },
  ]
}

resource "aws_ecs_task_definition" "crawler" {
  family                   = "twrh-crawler"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.crawler_cpu
  memory                   = var.crawler_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.crawler_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  volume {
    name = "shared"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.shared.id
      transit_encryption = "ENABLED"
    }
  }

  container_definitions = jsonencode([{
    name        = "crawler"
    image       = "${aws_ecr_repository.crawler.repository_url}:latest"
    essential   = true
    command     = ["./devop/orchestrate.sh"]
    environment = local.crawler_env
    secrets     = local.crawler_secrets
    mountPoints = local.mount_points
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.crawler.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "crawl"
      }
    }
  }])
}

# ---- 每日排程（A4 才 enable）----
resource "aws_scheduler_schedule" "daily_crawl" {
  count                        = var.enable_schedule ? 1 : 0
  name                         = "twrh-daily-crawl"
  schedule_expression          = var.crawl_schedule
  schedule_expression_timezone = "Asia/Taipei"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_ecs_cluster.twrh.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.crawler.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.task.id]
        assign_public_ip = true
      }
    }
  }
}

# ---- 月度 housekeep（raw offload ＋ HouseTS 歸檔，節省槓桿 1＋2）----
# 同一顆 image、command override；時間須避開爬蟲時段（rawoffload 無鎖）
resource "aws_scheduler_schedule" "monthly_housekeep" {
  count                        = var.enable_schedule ? 1 : 0
  name                         = "twrh-monthly-housekeep"
  schedule_expression          = var.housekeep_schedule
  schedule_expression_timezone = "Asia/Taipei"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_ecs_cluster.twrh.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.crawler.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.task.id]
        assign_public_ip = true
      }
    }
    input = jsonencode({
      containerOverrides = [{
        name    = "crawler"
        command = ["./devop/housekeep.sh"]
      }]
    })
  }
}

output "ecr_crawler_url" {
  value = aws_ecr_repository.crawler.repository_url
}

output "ecr_publisher_url" {
  value = aws_ecr_repository.publisher.repository_url
}

output "efs_id" {
  value = aws_efs_file_system.shared.id
}
