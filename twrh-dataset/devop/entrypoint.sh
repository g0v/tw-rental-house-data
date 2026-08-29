#!/bin/bash
# Fargate 上 EFS 掛在 /data（devop/aws/main.tf mount_points）；go.sh 與
# persist_queue 的路徑契約是 /app/logs（../logs）與 /app/twrh-dataset/datas。
# 開機時把兩者指到 EFS，progress 續跑、export 中繼檔才能跨 task 留存。
# 本機 docker run 沒掛 /data 時整段跳過（bind mount 慣例照舊）。
set -e
if [ -d /data ]; then
  mkdir -p /data/logs /data/datas
  ln -sfn /data/logs /app/logs
  rm -rf /app/twrh-dataset/datas
  ln -sfn /data/datas /app/twrh-dataset/datas
fi
exec "$@"
