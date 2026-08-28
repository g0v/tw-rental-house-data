# IAM：execution role（拉 image／寫 log／讀 SSM 機密）、task roles（最小權限）、
# scheduler role（只准 run 這個 task definition）。

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---- execution role：ECS agent 用 ----
resource "aws_iam_role" "execution" {
  name               = "twrh-execution${var.name_suffix}"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_ssm" {
  name = "read-twrh-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameters"]
      Resource = [for p in aws_ssm_parameter.secrets : p.arn]
    }]
  })
}

# ---- crawler task role：目前只需 ECS Exec（workbench 進 shell 用）----
resource "aws_iam_role" "crawler_task" {
  name               = "twrh-crawler-task${var.name_suffix}"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "crawler_exec" {
  name = "ecs-exec"
  role = aws_iam_role.crawler_task.id
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

# publisher task role（S3 出貨、raw offload 上傳）等 publisher task definition
# 一起加：s3:PutObject 限 twrh bucket 的 /<year>/* 與 raw offload prefix。

# ---- EventBridge Scheduler role ----
resource "aws_iam_role" "scheduler" {
  name = "twrh-scheduler${var.name_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_run_task" {
  name = "run-crawler-task"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = [aws_ecs_task_definition.crawler.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.execution.arn, aws_iam_role.crawler_task.arn]
      },
    ]
  })
}
