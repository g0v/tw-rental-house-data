#!/bin/bash
# D5 一次性清空（architecture-roadmap 3-1 切換）：DB 停寫 raw（TWRH_RAW_DB_WRITE=0
# 已上線且日跑綠）之後，把 house_etc 仍存的 detail_raw/list_raw 全部打包出 DB。
# 就是 housekeep 退役掉的 raw 半邊、窗口設 0 天——包格式與既有月包一致
# （raw/<vendor>/<YYYY-MM>[-n].tar.zst＋index.json，依 updated 月份分檔），
# 內容不丟：日包只從 9/4 起，之前爬、之後沒再爬的物件 raw 只在 DB。
#
# 用法（run-task 覆寫 command，一次只發一個；避開爬蟲時段——rawoffload
# 打包與清欄位之間沒有鎖）：
#   ./devop/rawcutover.sh            # dry-run：只打包＋驗證，不動 DB
#   ./devop/rawcutover.sh --commit   # 清欄位＋蓋 raw_archived_at，包上 S3
# 清完欄位 PostgreSQL 不會自動還空間：RDS 儲存量只升不降，表內空間要
# `VACUUM (FULL) house_etc`（鎖表數分鐘，挑閒時）才回收；不做也只是不縮。
set -uo pipefail
cd "$(dirname "$0")/.."
: "${TWRH_RAW_BUCKET:?}"
OUT=/data/housekeep
mkdir -p "$OUT/raw"
failed=0
commit="${1:-}"

s3put() {  # s3put <local-file> <s3-key> [STANDARD|GLACIER_IR]
  poetry run python -c "
import sys, os, boto3
local, key, sc = sys.argv[1], sys.argv[2], sys.argv[3]
boto3.client('s3').upload_file(local, os.environ['TWRH_RAW_BUCKET'], key,
                               ExtraArgs={'StorageClass': sc})
print('uploaded s3://{}/{}'.format(os.environ['TWRH_RAW_BUCKET'], key))
" "$1" "$2" "${3:-STANDARD}"
}

if [ "${TWRH_RAW_DB_WRITE:-1}" = "1" ] && [ "$commit" = "--commit" ]; then
  echo '!!! TWRH_RAW_DB_WRITE is still 1 (pipeline keeps writing raw to DB) — flip it first'
  exit 1
fi

echo "===== RAW CUTOVER (${commit:-dry-run}) ====="
poetry run python django/manage.py rawoffload "$OUT/raw" --days-ago 0 $commit \
  || { echo '!!! rawoffload failed'; failed=1; }

for f in "$OUT"/raw/*/*; do
  [ -e "$f" ] || continue
  vendor_dir=$(basename "$(dirname "$f")")
  vendor="${vendor_dir%% *}"   # '591 租屋網' -> '591'，對齊 raw/591/ 佈局
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

[ "$failed" = 1 ] && { echo '=== rawcutover done WITH ERRORS ==='; exit 1; }
echo '=== rawcutover done ==='
