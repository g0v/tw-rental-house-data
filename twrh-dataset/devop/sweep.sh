#!/bin/bash
# 前緣掃描（短命物件，#229 追查 2026-09-05）：清晨全量之外，每隔數小時掃各縣市
# list 的最前面幾頁（新刊登連續排在最前），對沒見過的物件立刻抓 detail——
# 刊登不到一天就成交的物件，一天一次 02:10 只看得到一半。
# 與日跑同一個日期 bucket、同一張 queue；被掃到的物件隔天早上因 detail 很新
# 會被 diff 判 skip，日跑反而更輕。排程須避開 02:00–05:00 主跑。
#   ./devop/sweep.sh            # TWRH_SWEEP_PAGES 每縣市頁數上限（預設 30）
set -uo pipefail
cd "$(dirname "$0")/.."
now=$(date +%Y%m%d-%H%M)
echo "=== sweep $now (frontier pages<=${TWRH_SWEEP_PAGES:-30}) ==="
breaker_tripped() { grep -q 'error_rate_exceeded' "$1"; }

# 互斥：同一張 queue、同一日期 bucket，別人（拖長的日跑、臨時 run-task 測試）
# 正在爬就讓路——以「當日有 2 小時內更新過的 in_flight 列」判定，避免被
# SIGKILL 殘留的舊 in_flight 永久擋住。讓路＝exit 0 不告警，下一輪再來。
if poetry run python ./django/manage.py shell -c '
import sys
from datetime import timedelta
from django.utils import timezone
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestStatus
import os
from datetime import datetime
override = os.environ.get("TWRH_TARGET_DATE")
today = datetime.strptime(override, "%Y-%m-%d").date() if override else timezone.localtime().date()
y, m, d, h = today.year, today.month, today.day, 0
busy = RequestTS.objects.filter(
    year=y, month=m, day=d, hour=h, status=RequestStatus.IN_FLIGHT,
    updated__gte=timezone.now() - timedelta(hours=2)).count()
print("in_flight(<2h):", busy)
sys.exit(1 if busy else 0)
'; then :; else
  echo '=== sweep skipped: another crawl is in flight on this queue ==='; exit 0
fi

echo '===== FRONTIER LIST ====='
export TWRH_CONCURRENT_REQUESTS="${TWRH_SWEEP_CONCURRENCY:-2}"
export TWRH_DOWNLOAD_DELAY="${TWRH_SWEEP_DELAY:-0.5}"
poetry run scrapy crawl list591 -L INFO -a frontier_pages="${TWRH_SWEEP_PAGES:-30}"
mv scrapy.log "../logs/$now.sweep-list.log"
if breaker_tripped "../logs/$now.sweep-list.log"; then
  echo '!!! sweep list breaker tripped — abort'; exit 1
fi
grep -o '\[frontier\] [0-9]* unseen houses discovered' "../logs/$now.sweep-list.log" || true

# 保守速率：白天與使用者共用站方資源，且 sweep 試跑（09-05）在 1,500 筆
# 全速 detail 後吃到連續 403——比主跑的速率參數更溫和
export TWRH_CONCURRENT_REQUESTS="${TWRH_SWEEP_CONCURRENCY:-2}"
export TWRH_DOWNLOAD_DELAY="${TWRH_SWEEP_DELAY:-0.5}"

echo '===== NEW DETAIL ====='
# 兩趟：第二趟只會撿第一趟 failed 的重試（seed_mode=new 不重排當日已有列的物件）
for pass in 1 2; do
  poetry run scrapy crawl detail591 -L INFO -a seed_mode=new
  mv scrapy.log "../logs/$now.sweep-detail.$pass.log"
  if breaker_tripped "../logs/$now.sweep-detail.$pass.log"; then
    echo '!!! sweep detail breaker tripped — abort before finalize'; exit 1
  fi
  grep -E 'generating request|response_status_count|item_scraped_count' "../logs/$now.sweep-detail.$pass.log" | sed 's/^.*INFO: //' | tr -d ' ,' | tr '\n' ' '; echo
done

# 同日 queue 一併對帳（含清晨那輪，已全 done）；紅＝本輪殘留，Slack 有訊息
echo '===== QUEUE FINALIZE ====='
poetry run python ./django/manage.py queuefinalize --no-cleanup || exit 1
echo "=== sweep $now done ==="
