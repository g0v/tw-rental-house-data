#!/bin/bash
# sync-dev-data：拉回開發用資料分區（architecture-roadmap 3-3 零雲相依）。
#
# 對象＝有 bucket 讀權限的專案成員（可散佈界線拍板：一般貢獻者以
# twrh CLI 自抓資料開發，不經此路）。拉回後不需 PostGIS 即可：
#   - tools/quality_offline.py    重跑品質斷言（manifests/）
#   - tools/rerun_from_raws.py    重放 parser（raws/，dry-run 無 DB 寫入*）
#   * commit 模式寫 DB，仍需本機 DB
#
# 用法：
#   TWRH_RAW_BUCKET=twrh-w2 ./tools/sync-dev-data.sh [dest-dir] [raw-days]
#   dest-dir 預設 repo 的 twrh-dataset/；raw-days 預設 0（只拉 manifests）
set -euo pipefail

BUCKET="${TWRH_RAW_BUCKET:?set TWRH_RAW_BUCKET (e.g. twrh-w2)}"
DEST="${1:-$(dirname "$0")/..}"
RAW_DAYS="${2:-0}"

echo "=== sync manifests/ ==="
aws s3 sync "s3://$BUCKET/manifests/" "$DEST/manifests/"

if [ "$RAW_DAYS" -gt 0 ]; then
  echo "=== sync raw packs (last $RAW_DAYS days) ==="
  includes=()
  for ((i = 0; i < RAW_DAYS; i++)); do
    d=$(date -d "-$i day" +%F)
    includes+=(--include "*/$d.tar.zst" --include "*/$d.index.jsonl")
  done
  aws s3 sync "s3://$BUCKET/raw/" "$DEST/raws/" --exclude '*' "${includes[@]}"
fi
echo "=== done ==="
