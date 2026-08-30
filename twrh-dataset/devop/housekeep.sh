#!/bin/bash
# 月度 DB 瘦身（docs/aws-deployment-plan「三個節省槓桿」1＋2）：
#   1. rawoffload：保留窗口外的 detail_raw/list_raw 打包 tar.zst、清欄位，
#      包上傳 S3（tar.zst 走 Glacier IR、index json 走 STANDARD）
#   2. archivehistory：窗口外的 HouseTS dump＋刪列，tgz 上傳 S3
# 上傳成功才刪 EFS 上的本地檔——上傳失敗時檔案留著，下次執行重送。
# 排程須避開爬蟲時段（rawoffload 與爬蟲之間沒有鎖）；S3 端無 DeleteObject，
# 刪除永遠人工（見 devop/aws/s3.tf）。
set -uo pipefail
cd "$(dirname "$0")/.."   # -> /app/twrh-dataset

: "${TWRH_RAW_BUCKET:?}"
WINDOW_DAYS="${TWRH_HOUSEKEEP_DAYS:-90}"
OUT=/data/housekeep
mkdir -p "$OUT/raw" "$OUT/ts"
failed=0

s3put() {  # s3put <local-file> <s3-key> [STANDARD|GLACIER_IR]
  poetry run python -c "
import sys, os, boto3
local, key, sc = sys.argv[1], sys.argv[2], sys.argv[3]
boto3.client('s3').upload_file(local, os.environ['TWRH_RAW_BUCKET'], key,
                               ExtraArgs={'StorageClass': sc})
print('uploaded s3://{}/{}'.format(os.environ['TWRH_RAW_BUCKET'], key))
" "$1" "$2" "${3:-STANDARD}"
}

echo '===== RAW OFFLOAD ====='
poetry run python django/manage.py rawoffload "$OUT/raw" --days-ago "$WINDOW_DAYS" --commit \
  || { echo '!!! rawoffload failed'; failed=1; }

for f in "$OUT"/raw/*/*; do
  [ -e "$f" ] || continue
  vendor_dir=$(basename "$(dirname "$f")")
  vendor="${vendor_dir%% *}"   # '591 租屋網' -> '591'，對齊既有 raw/591/ 佈局
  base=$(basename "$f")
  case "$base" in
    *.tar.zst) sc=GLACIER_IR ;;
    *)         sc=STANDARD ;;
  esac
  if s3put "$f" "raw/$vendor/$base" "$sc"; then
    rm "$f"
  else
    echo "!!! upload failed, keep $f for next run"
    failed=1
  fi
done

echo '===== HOUSE_TS ARCHIVE ====='
poetry run python django/manage.py archivehistory "$OUT/ts" -d "$WINDOW_DAYS" \
  || { echo '!!! archivehistory failed'; failed=1; }

for f in "$OUT"/ts/compressed/*.tgz; do
  [ -e "$f" ] || continue
  if s3put "$f" "archive/house_ts/$(basename "$f")" GLACIER_IR; then
    rm "$f"
  else
    echo "!!! upload failed, keep $f for next run"
    failed=1
  fi
done

[ "$failed" = 1 ] && { echo '=== housekeep done WITH ERRORS ==='; exit 1; }
echo '=== housekeep done ==='
