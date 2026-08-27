#!/bin/bash

usage() {
    cat <<'USAGE'
Usage: ./gobg.sh [OPTIONS]

Run go.sh in the background (detached via setsid).
All arguments are passed through to go.sh.

Options:
  --append        Append mode (see go.sh --help)
  --start-early   Start-early mode (see go.sh --help)
  --date DATE     Pin the target date (YYYY-MM-DD) (see go.sh --help)
  -h, --help      Show this help message and exit

Output is logged to ../logs/<timestamp>.go.log
Also starts watchdog.sh alongside (heartbeat/progress/error monitoring,
logs to ../logs/<timestamp>.watchdog; Slack on anomaly & finish).
USAGE
    exit 0
}

# Check for help flag before passing through
for arg in "$@"; do
    case $arg in
        -h|--help) usage ;;
    esac
done

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR
mkdir -p ../logs

TS=`date +'%Y.%m.%d.%H%M'`
GO_LOG=../logs/$TS.go.log
PID_FILE=../logs/$TS.go.pid

# Pass through all arguments (--append, --start-early, --date, etc.)
# setsid 可能會 fork，$! 不可靠 —— 由子 shell 自己寫 pidfile 交給 watchdog
setsid bash -c 'echo $$ > "$0"; exec ./go.sh "$@"' "$PID_FILE" "$@" >> $GO_LOG 2>&1 &

# 隨行監控（.watchdog 不用 .log 結尾，避開 go.sh FINALIZE 的 gzip ../logs/*.log）
setsid ./watchdog.sh --pid-file "$PID_FILE" --log "$GO_LOG" >> ../logs/$TS.watchdog 2>&1 &
echo "pipeline log: $GO_LOG"
echo "watchdog log: ../logs/$TS.watchdog"
