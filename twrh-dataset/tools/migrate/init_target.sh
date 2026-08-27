#!/bin/bash
# 建目標 DB＋複製 schema（schema parity 由 pg_dump 保證，不經 Django migrate）。
# 用法：PGPASSWORD=xx ./init_target.sh <source_db> <target_db> [pg 連線參數…]
#   例：PGPASSWORD=1234 ./init_target.sh twrh2025 twrh_new -h 127.0.0.1 -U postgres
set -e
SRC=$1; DST=$2; shift 2
createdb "$@" "$DST"
pg_dump "$@" --schema-only "$SRC" | psql -q "$@" "$DST"
echo "target $DST ready (schema copied from $SRC)"
