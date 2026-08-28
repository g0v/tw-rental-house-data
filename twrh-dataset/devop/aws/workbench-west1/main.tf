# M1 臨時 workbench（us-west-1，舊 RDS 所在區）——盤查／遷移歷史段用，
# M4 切換驗證完成後整組 destroy。與 ../（正式區 us-west-2）分開 state。
#
# 設計要點：
# - 不建新 SG、不改舊 RDS 的 SG：task 直接掛現成的 ec2-rds-1（RDS 進入規則
#   放行它）＋ default（全 egress，拉 image／寫 log／SSM 用）。
# - 舊 DB 密碼由 terraform 從 devop/master/settings_local.py 讀出寫入
#   SSM SecureString，不經 shell、不進 git（state 檔已 gitignore）。
# - image 用正式區（us-west-2）ECR 的 twrh-crawler，跨區拉取（付少量流量費，
#   免在 us-west-1 多養一份 ECR）。
# - IAM role 沿用正式區的 twrh-execution / twrh-crawler-task（IAM 全域），
#   只補一條讀 us-west-1 密碼參數的 role policy。

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
  region = "us-west-1"
  default_tags {
    tags = { project = "twrh" }
  }
}

locals {
  old_db_password = regex("'PASSWORD':\\s*'([^']+)'", file("${path.module}/../../master/settings_local.py"))[0]
  crawler_image   = "846793362148.dkr.ecr.us-west-2.amazonaws.com/twrh-crawler:latest"
}

data "aws_iam_role" "execution" {
  name = "twrh-execution"
}

data "aws_iam_role" "crawler_task" {
  name = "twrh-crawler-task"
}

resource "aws_ssm_parameter" "old_db_password" {
  name  = "/twrh/old-db-password"
  type  = "SecureString"
  value = local.old_db_password
}

resource "aws_iam_role_policy" "execution_old_db_password" {
  name = "read-old-db-password-west1"
  role = data.aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameters"]
      Resource = [aws_ssm_parameter.old_db_password.arn]
    }]
  })
}

resource "aws_cloudwatch_log_group" "workbench" {
  name              = "/twrh/workbench"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "workbench" {
  name = "twrh-workbench"
}

resource "aws_ecs_task_definition" "workbench" {
  family                   = "twrh-workbench"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = data.aws_iam_role.execution.arn
  task_role_arn            = data.aws_iam_role.crawler_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "workbench"
    image     = local.crawler_image
    essential = true
    command   = ["sleep", "infinity"] # 實際工作以 RunTask command override 指定
    environment = [
      { name = "PGHOST", value = "twrh.cfes86a82zjg.us-west-1.rds.amazonaws.com" },
      { name = "PGDATABASE", value = "twrh" },
      { name = "PGUSER", value = "twrh" },
      { name = "PGCONNECT_TIMEOUT", value = "10" },
    ]
    secrets = [
      { name = "PGPASSWORD", valueFrom = aws_ssm_parameter.old_db_password.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.workbench.name
        awslogs-region        = "us-west-1"
        awslogs-stream-prefix = "wb"
      }
    }
  }])
}

# RunTask 用的固定參數（public /20 subnet 走 igw；private /25 是 RDS 的家）
output "run_task_hint" {
  value = "aws ecs run-task --cluster twrh-workbench --launch-type FARGATE --task-definition twrh-workbench --network-configuration 'awsvpcConfiguration={subnets=[subnet-07549db037dbf8cbb],securityGroups=[sg-01c13576fe0ba7233,sg-01d6ffe5b75143384],assignPublicIp=ENABLED}'"
}
