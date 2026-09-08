#!/bin/bash
# 月度 DB 瘦身（docs/aws-deployment-plan「三個節省槓桿」2；槓桿 1 的 raw
# offload 已於 D5 退役，raw 改由 rawpack 每日直寫 S3）：
#   archivehistory：窗口外的 HouseTS dump＋刪列，tgz 上傳 S3
# 上傳成功才刪 EFS 上的本地檔——上傳失敗時檔案留著，下次執行重送。
# 排程須避開爬蟲時段；S3 端無 DeleteObject，刪除永遠人工（見 devop/aws/s3.tf）。
set -uo pipefail
cd "$(dirname "$0")/.."   # -> /app/twrh-dataset

: "${TWRH_RAW_BUCKET:?}"
WINDOW_DAYS="${TWRH_HOUSEKEEP_DAYS:-90}"
OUT=/data/housekeep
mkdir -p "$OUT/ts"
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

# raw 半邊已退役（D5，2026-09-05）：DB 不再存 raw，日包由 rawpack 每日直寫 S3；
# raw 欄位已於 D5（2026-09-07）清空並在 Phase 4 清理 migration drop

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
