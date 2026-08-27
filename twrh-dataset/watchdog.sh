#!/bin/bash
# 隨行監控 go.sh pipeline：心跳、進度、錯誤量、收尾斷言。
# 由 gobg.sh 與 go.sh 一起拉起（見 gobg.sh），也可手動監看一個跑到一半的 pipeline：
#   ./watchdog.sh --pid-file ../logs/<ts>.go.pid --log ../logs/<ts>.go.log
#
# 設計原則：正常時安靜（只寫自己的 stdout log），異常與收尾才發 Slack。
# 偵測不介入 —— 不殺、不重啟 pipeline。

usage() {
    cat <<'USAGE'
Usage: ./watchdog.sh --pid-file FILE --log FILE [OPTIONS]

Options:
  --pid-file FILE   go.sh 的 pidfile（gobg.sh 產生）
  --log FILE        go.sh 的 stdout log（<ts>.go.log）
  --interval SEC    檢查間隔，預設 300
  -h, --help        Show this help
USAGE
    exit 0
}

PID_FILE=""
GO_LOG=""
INTERVAL=300

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help) usage ;;
        --pid-file) PID_FILE="$2"; shift 2 ;;
        --log) GO_LOG="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; shift ;;
    esac
done

[ -z "$PID_FILE" ] || [ -z "$GO_LOG" ] && { echo "--pid-file and --log are required"; exit 2; }

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# ---- 參數（可由環境變數覆寫）----
STALL_LIMIT=${WATCHDOG_STALL_LIMIT:-900}        # LIST/DETAIL 階段：log/進度多久沒動視為卡住（秒）
QUIET_LIMIT=${WATCHDOG_QUIET_LIMIT:-7200}       # SYNC/STATS/EXPORT 階段：單一階段最長時間（秒）
ERR_LIMIT=${WATCHDOG_ERR_LIMIT:-30}             # 單一 scrapy batch 內 ERROR/CRITICAL 行數上限
HTTP403_LIMIT=${WATCHDOG_403_LIMIT:-100}        # 單一 scrapy batch 內 403 次數上限
ALERT_COOLDOWN=${WATCHDOG_ALERT_COOLDOWN:-1800} # 同類告警最短間隔（秒）
MAX_LIFETIME=$((24 * 3600))                     # watchdog 自身最長壽命

log() { echo "[$(date +'%F %T')] $*"; }

# Slack webhook：優先吃環境變數，否則從 settings_local.py 撈
slack_webhook() {
    if [ -n "$TWRH_SLACK_WEBHOOK" ]; then
        echo "$TWRH_SLACK_WEBHOOK"
    else
        sed -n "s/^SLACK_WEBHOOK_URL = '\(.*\)'/\1/p" django/backend/settings_local.py 2>/dev/null
    fi
}

json_escape() {
    local s=${1//\\/\\\\}
    s=${s//\"/\\\"}
    printf '%s' "$s"
}

notify() {
    local msg="🐶 watchdog | $*"
    log "SLACK: $*"
    local hook
    hook=$(slack_webhook)
    [ -z "$hook" ] && return 0
    curl -s -m 10 -X POST -H 'Content-Type: application/json' \
        -d "{\"text\": \"$(json_escape "$msg")\"}" \
        "$hook" > /dev/null 2>&1 || log "WARN: Slack 通知失敗"
}

# go.log 在 FINALIZE 會被 gzip（連自己都 gzip 是 go.sh 既有行為），兩種都要能讀
read_go_log() {
    if [ -f "$GO_LOG" ]; then
        cat "$GO_LOG"
    elif [ -f "$GO_LOG.gz" ]; then
        zcat "$GO_LOG.gz"
    fi
}

current_stage() {
    read_go_log | grep -oE '^===== [A-Z ]+ =====$' | tail -1 | tr -d '=' | xargs
}

# 告警冷卻：同 key 在 cooldown 內不重發
declare -A LAST_ALERT
alert() {
    local key="$1"; shift
    local now=$(date +%s)
    local last=${LAST_ALERT[$key]:-0}
    if (( now - last >= ALERT_COOLDOWN )); then
        LAST_ALERT[$key]=$now
        notify "⚠️ $*"
    else
        log "(cooldown) $*"
    fi
}

# ---- 等 pidfile 與 TARGET DATE 出現 ----
GO_PID=""
for i in $(seq 1 30); do
    [ -f "$PID_FILE" ] && GO_PID=$(cat "$PID_FILE") && [ -n "$GO_PID" ] && break
    sleep 2
done
if [ -z "$GO_PID" ]; then
    notify "🚨 啟動失敗：等不到 pidfile $PID_FILE，pipeline 可能根本沒開跑"
    exit 1
fi

TARGET_DATE=""
for i in $(seq 1 30); do
    TARGET_DATE=$(read_go_log | sed -n 's/^Running with TARGET DATE: //p' | head -1)
    [ -n "$TARGET_DATE" ] && break
    kill -0 "$GO_PID" 2>/dev/null || break
    sleep 2
done

PROGRESS_FILE="../logs/progress/$TARGET_DATE.detail.json"
START_TS=$(date +%s)
if (( INTERVAL >= 60 )); then INTERVAL_DESC="$((INTERVAL / 60)) 分鐘"; else INTERVAL_DESC="$INTERVAL 秒"; fi
notify "已開始監控 pipeline（pid $GO_PID，target date ${TARGET_DATE:-unknown}，每 $INTERVAL_DESC 檢查）"

# ---- 主迴圈 ----
LAST_PROGRESS=-1
PROGRESS_STUCK_ROUNDS=0
LAST_STAGE=""
STAGE_START=$START_TS
BREAKER_REPORTED=0

while true; do
    NOW=$(date +%s)

    # 自身壽命保險
    if (( NOW - START_TS > MAX_LIFETIME )); then
        notify "🚨 watchdog 已運轉超過 24 小時，pipeline 仍未結束，放棄監控（pipeline 未動）"
        exit 1
    fi

    # ---- pipeline 結束：收尾斷言 ----
    if ! kill -0 "$GO_PID" 2>/dev/null; then
        sleep 5  # 讓 FINALIZE 的 gzip 收完
        ELAPSED_MIN=$(( (NOW - START_TS) / 60 ))
        FULL_LOG=$(read_go_log)
        PROG_SUMMARY=""
        if [ -f "$PROGRESS_FILE" ]; then
            PROG_SUMMARY=$(cat "$PROGRESS_FILE")
        fi
        ERROR_FILE=$(ls -t ../logs/*.error 2>/dev/null | head -1)
        ERR_LINES=0
        [ -n "$ERROR_FILE" ] && ERR_LINES=$(wc -l < "$ERROR_FILE")

        if echo "$FULL_LOG" | grep -q '^===== FINALIZE ====='; then
            # FINALIZE 只代表流程走完，不代表有產出 —— 0 完成數的「正常收尾」
            # 是假成功（例：scrapy 2.18 不再呼叫 start_requests，spider 靜默秒收）
            FINAL_COMPLETED=$(sed -n 's/.*"completed": \([0-9]*\).*/\1/p' "$PROGRESS_FILE" 2>/dev/null)
            if [ -z "$FINAL_COMPLETED" ] || (( FINAL_COMPLETED == 0 )); then
                notify "🚨 pipeline 走完 FINALIZE 但近乎零產出（$TARGET_DATE，歷時 ${ELAPSED_MIN} 分，progress: ${PROG_SUMMARY:-檔案不存在}）——疑似靜默失敗，請查 $GO_LOG"
            else
                notify "✅ pipeline 正常收尾（$TARGET_DATE，歷時 ${ELAPSED_MIN} 分）。progress: ${PROG_SUMMARY:-n/a}；error log 行數: $ERR_LINES（$ERROR_FILE）"
            fi
        elif echo "$FULL_LOG" | grep -q 'Breaker tripped'; then
            notify "🚨 pipeline 被熔斷中止（error_rate_exceeded，$TARGET_DATE，歷時 ${ELAPSED_MIN} 分）。progress: ${PROG_SUMMARY:-n/a}。請查 $GO_LOG"
        else
            LAST_LINES=$(echo "$FULL_LOG" | tail -5 | tr '\n' ' | ')
            notify "🚨 pipeline 異常終止於「${LAST_STAGE:-unknown}」階段（$TARGET_DATE，歷時 ${ELAPSED_MIN} 分），log 沒有 FINALIZE。最後輸出：$LAST_LINES"
        fi
        exit 0
    fi

    # ---- 熔斷訊號（在 go.sh exit 前就先知道）----
    if [ "$BREAKER_REPORTED" = 0 ] && read_go_log | grep -q 'error_rate_exceeded'; then
        BREAKER_REPORTED=1
        alert breaker "偵測到 error_rate_exceeded，熔斷可能已觸發或即將觸發"
    fi

    STAGE=$(current_stage)
    if [ "$STAGE" != "$LAST_STAGE" ]; then
        log "階段切換: ${LAST_STAGE:-（啟動）} -> ${STAGE:-unknown}"
        LAST_STAGE="$STAGE"
        STAGE_START=$NOW
    fi

    # ---- 心跳與進度 ----
    NEWEST_MTIME=0
    for f in scrapy.log "$GO_LOG" "$PROGRESS_FILE"; do
        [ -f "$f" ] || continue
        M=$(stat -c %Y "$f")
        (( M > NEWEST_MTIME )) && NEWEST_MTIME=$M
    done
    IDLE=$(( NOW - NEWEST_MTIME ))

    PROG_LINE=""
    case "$STAGE" in
        LIST|DETAIL)
            if (( NEWEST_MTIME > 0 && IDLE > STALL_LIMIT )); then
                alert stall "「$STAGE」階段疑似卡住：log/進度已 $((IDLE / 60)) 分鐘沒有更新（pid $GO_PID 仍存活）"
            fi
            if [ "$STAGE" = DETAIL ] && [ -f "$PROGRESS_FILE" ]; then
                COMPLETED=$(sed -n 's/.*"completed": \([0-9]*\).*/\1/p' "$PROGRESS_FILE")
                TOTAL=$(sed -n 's/.*"total": \([0-9]*\).*/\1/p' "$PROGRESS_FILE")
                if [ -n "$COMPLETED" ]; then
                    if (( LAST_PROGRESS >= 0 )); then
                        RATE=$(( (COMPLETED - LAST_PROGRESS) * 60 / INTERVAL ))
                        PROG_LINE="progress $COMPLETED/$TOTAL（$RATE 筆/分）"
                        if (( COMPLETED == LAST_PROGRESS )); then
                            PROGRESS_STUCK_ROUNDS=$((PROGRESS_STUCK_ROUNDS + 1))
                            if (( PROGRESS_STUCK_ROUNDS >= 3 )); then
                                alert progress "DETAIL 進度停滯：completed 連 $PROGRESS_STUCK_ROUNDS 輪（$(( PROGRESS_STUCK_ROUNDS * INTERVAL / 60 )) 分鐘）維持在 $COMPLETED/$TOTAL"
                            fi
                        else
                            PROGRESS_STUCK_ROUNDS=0
                        fi
                    else
                        PROG_LINE="progress $COMPLETED/$TOTAL"
                    fi
                    LAST_PROGRESS=$COMPLETED
                fi
            fi
            ;;
        *)
            # SYNC/STATS/EXPORT 等安靜階段：只看單階段 wall-clock
            if [ -n "$STAGE" ] && (( NOW - STAGE_START > QUIET_LIMIT )); then
                alert quiet_stage "「$STAGE」階段已跑超過 $(( (NOW - STAGE_START) / 60 )) 分鐘，超出預期"
            fi
            ;;
    esac

    # ---- 錯誤量（當前 scrapy batch）----
    ERRS=0; H403=0
    if [ -f scrapy.log ]; then
        ERRS=$(grep -cE '\] (ERROR|CRITICAL)' scrapy.log)
        H403=$(grep -c ' 403 ' scrapy.log)
        (( ERRS >= ERR_LIMIT )) && alert errors "當前 scrapy.log 已有 $ERRS 行 ERROR/CRITICAL（門檻 $ERR_LIMIT）"
        (( H403 >= HTTP403_LIMIT )) && alert http403 "當前 scrapy.log 已出現 $H403 次 403（門檻 $HTTP403_LIMIT），可能被擋"
    fi

    log "stage=${STAGE:-starting} ${PROG_LINE:+$PROG_LINE }idle=${IDLE}s err=$ERRS 403=$H403"
    sleep "$INTERVAL"
done
