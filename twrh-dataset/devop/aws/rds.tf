# 新 RDS（aws-deployment-plan「資料遷移」的目的地）。
# 預設不建（enable_rds=false）——apply 前先人工把 /twrh/db-password 填成真值
# （master 密碼取自該參數，terraform 只在建立時讀一次），再以
# `-var enable_rds=true` 開起來。deletion_protection 常開：destroy／換機
# 一律先人工解鎖，呼應「破壞性操作永遠人工」。

data "aws_ssm_parameter" "db_password" {
  name            = aws_ssm_parameter.secrets["db-password"].name
  with_decryption = true
}

resource "aws_db_subnet_group" "twrh" {
  count      = var.enable_rds ? 1 : 0
  name       = "twrh"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "rds" {
  count       = var.enable_rds ? 1 : 0
  name_prefix = "twrh-rds-"
  vpc_id      = data.aws_vpc.default.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }
}

resource "aws_db_instance" "twrh" {
  count      = var.enable_rds ? 1 : 0
  identifier = "twrh"

  engine         = "postgres"
  engine_version = "15"
  instance_class = var.rds_instance_class

  # M1 實測：瘦身後歷史段＋本機段穩態遠小於 50 GB；gp3 基準 3000 IOPS
  allocated_storage     = 50
  max_allocated_storage = 80
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "twrh"
  username = "twrh"
  password = data.aws_ssm_parameter.db_password.value

  db_subnet_group_name   = aws_db_subnet_group.twrh[0].name
  vpc_security_group_ids = [aws_security_group.rds[0].id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 7
  deletion_protection     = true
  skip_final_snapshot     = false
  final_snapshot_identifier = "twrh-final"

  auto_minor_version_upgrade = true

  lifecycle {
    ignore_changes = [password] # 上線後密碼輪替走人工，terraform 不追
  }
}

output "rds_endpoint" {
  value = var.enable_rds ? aws_db_instance.twrh[0].address : null
}
