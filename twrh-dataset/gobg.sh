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

# Pass through all arguments (--append, --start-early, --date, etc.)
setsid ./go.sh "$@" >> ../logs/`date +'%Y.%m.%d.%H%M'`.go.log 2>&1 &
