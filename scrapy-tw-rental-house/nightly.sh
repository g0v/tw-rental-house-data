#!/bin/bash
# 三層 nightly 的可連網那半（docs/dx-roadmap.md 3-2）——公開 CI 只跑 L1 離線 golden，
# 這支跑需要連網的 L2/L3：
#
#   L1  pytest 離線 golden        —— 本機的改動有沒有弄壞 parser
#   L2  twrh probe 花蓮縣         —— 591 還讓不讓爬、selector 有沒有漂移
#   L3  probe --baseline 漂移比對 —— 591 變了沒（填充率 vs committed baseline）
#   L3b survey --baseline 不變量  —— 分佈形狀變了沒（樓層中位數、型態占比、頂加率）
#
# 只讀不寫：不碰 DB、不碰 fixture。失敗以 exit code 回報；
# 設 TWRH_SLACK_WEBHOOK 時，失敗會多發一則 Slack 通知。
#
# 目前為**手動、偶爾執行**（本機不排 cron）；轉正式環境後再掛真的 nightly cron：
#   15 3 * * *  <repo>/scrapy-tw-rental-house/nightly.sh >> <repo>/logs/nightly/cron.log 2>&1
set -uo pipefail
cd "$(dirname "$0")"

CITY=${TWRH_PROBE_CITY:-花蓮縣}
BASELINE=${TWRH_PROBE_BASELINE:-baselines/hualien-fill-rate.json}
INVARIANTS=${TWRH_INVARIANTS_BASELINE:-baselines/2026-08-26.hualien.json}
LOG_DIR=${TWRH_NIGHTLY_LOG_DIR:-../logs/nightly}
mkdir -p "$LOG_DIR"
log_file="$LOG_DIR/$(date +%F).log"

fail=0
{
    echo "===== nightly $(date -Is) ====="

    echo "--- L1: pytest（離線 golden）---"
    poetry run pytest -q || fail=1

    echo "--- L2+L3: twrh probe $CITY（live 比率斷言 + baseline 漂移）---"
    poetry run twrh probe "$CITY" --baseline "$BASELINE" || fail=1

    echo "--- L3b: twrh survey $CITY（分佈不變量 vs committed baseline）---"
    poetry run twrh survey "$CITY" --baseline "$INVARIANTS" --out "$LOG_DIR/survey" || fail=1

    echo "===== result: $([ $fail -eq 0 ] && echo PASS || echo FAIL) ====="
} 2>&1 | tee -a "$log_file"

if [ $fail -ne 0 ] && [ -n "${TWRH_SLACK_WEBHOOK:-}" ]; then
    curl -sf -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"🌙 twrh nightly FAIL（$(date +%F)），詳見 $log_file\"}" \
        "$TWRH_SLACK_WEBHOOK" > /dev/null || true
fi

exit $fail
