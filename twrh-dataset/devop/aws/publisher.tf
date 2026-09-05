# publisher 雲化（aws-deployment-plan〈publisher 雲化〉，2026-09-05 拍板 state over S3）：
# 同一顆 image 的 publisher target（crawler＋clickhouse/awscli/git），掛同一份 EFS
# （export -p 產的月 zip 在 /data/datas），publish.sh 的 state／report／聚合產物
# 同步到 raw bucket 的 publish-state/，紅燈月人工補敘事後任一環境 --resume。
# 步驟 5 的 commit／push 以 SSM 的 github-deploy-key 淺 clone master。

resource "aws_cloudwatch_log_group" "publisher" {
  name              = "/twrh/publisher"
  retention_in_days = 90
}

resource "aws_iam_role" "publisher_task" {
  name               = "twrh-publisher-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "publisher_exec" {
  name = "ecs-exec"
  role = aws_iam_role.publisher_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
      ]
      Resource = "*"
    }]
  })
}

# 公開 bucket：只准放 /<year>/*（月 zip）＋驗 size 的 head；state 目錄讀寫；無刪除
resource "aws_iam_role_policy" "publisher_s3" {
  name = "publish-upload"
  role = aws_iam_role.publisher_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = ["arn:aws:s3:::${var.public_bucket}/2*/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${var.public_bucket}", aws_s3_bucket.raw.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = ["${aws_s3_bucket.raw.arn}/publish-state/*"]
      },
    ]
  })
}

locals {
  publisher_env = concat(local.crawler_env, [
    { name = "TWRH_PUBLISH_STATE_BUCKET", value = aws_s3_bucket.raw.bucket },
  ])
  publisher_secrets = concat(local.crawler_secrets, [
    { name = "TWRH_GITHUB_DEPLOY_KEY", valueFrom = aws_ssm_parameter.secrets["github-deploy-key"].arn },
  ])
}

resource "aws_ecs_task_definition" "publisher" {
  family                   = "twrh-publisher"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.publisher_cpu
  memory                   = var.publisher_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.publisher_task.arn

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
    name        = "publisher"
    image       = "${aws_ecr_repository.publisher.repository_url}:latest"
    essential   = true
    command     = ["./publish.sh"]
    environment = local.publisher_env
    secrets     = local.publisher_secrets
    mountPoints = local.mount_points
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.publisher.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "publish"
      }
    }
  }])
}

# 每月 1 日出上個月（publish.sh 預設 YYYYMM＝上月）；綠燈全自動，
# 紅燈停在敘事關卡→人工補完後 devop/aws/publish-cloud.sh YYYYMM --resume --quality-issue <id>
resource "aws_scheduler_schedule" "monthly_publish" {
  count                        = var.enable_publish_schedule ? 1 : 0
  name                         = "twrh-monthly-publish"
  schedule_expression          = var.publish_schedule
  schedule_expression_timezone = "Asia/Taipei"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_ecs_cluster.twrh.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      task_definition_arn    = aws_ecs_task_definition.publisher.arn
      launch_type            = "FARGATE"
      enable_execute_command = true
      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.task.id]
        assign_public_ip = true
      }
    }
  }
}
