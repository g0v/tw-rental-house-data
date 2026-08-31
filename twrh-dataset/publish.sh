#!/bin/bash
# 月度出貨（docs/export-automation-plan 目標流程；P2–P4）。
# 觸發永遠人工（本機一行）；流程自動、紅綠分岔：
#   1 聚合   dedup-single（季末加 merge-and-dedup、年末再跑年度）
#   2 驗證   check.sh ＋ monthreport（quality gate：紅=exit 2）
#   3 上傳   aws --profile twrh s3 cp → s3://twrh/<year>/（上傳後驗 size）
#   4 UI 列  tools/publish_ui_stats.py 寫 ui-next stats json
#   5 出貨   commit＋直 push master（紅綠皆同——2026-08-31 拍板：紅月的 --resume
#            本身就是人工確認，不再走 PR）；紅→首跑不 push，人工寫敘事後
#            `--resume --quality-issue <id>` 續跑 3–5 帶標記出貨
# 冪等：每步完成寫 marker 到 datas/publish/<YYYYMM>.state.json，--resume 跳過已完成步。
#
# 用法：./publish.sh [YYYYMM] [--resume] [--dry-run] [--quality-issue <id>] [--comment <md>]
#   YYYYMM 預設上個月；--dry-run 時 S3 用 --dryrun、git 不 push（P5 演練用）。
set -uo pipefail
cd "$(dirname "$0")"

YM=""; RESUME=0; DRYRUN=0; QISSUE=""; COMMENT=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --resume) RESUME=1; shift ;;
    --dry-run) DRYRUN=1; shift ;;
    --quality-issue) QISSUE="$2"; shift 2 ;;
    --comment) COMMENT="$2"; shift 2 ;;
    *) YM="$1"; shift ;;
  esac
done
[ -z "$YM" ] && YM=$(date -d "$(date +%Y-%m-01) -1 month" +%Y%m)
YEAR=${YM:0:4}; MONTH=${YM:4:2}
AGG=../csv-aggregator
DATAS=datas
STATE_DIR=$DATAS/publish
STATE=$STATE_DIR/$YM.state.json
RAW_ZIP="$DATAS/[${YM}][CSV][Raw] TW-Rental-Data.zip"
DEDUP_ZIP="$DATAS/[${YM}][CSV][Deduplicated] TW-Rental-Data.zip"
JSON_ZIP="$DATAS/[${YM}][JSON][Raw] TW-Rental-Data.zip"
S3_BUCKET=twrh   # 公開資料集 bucket（ap-northeast-3）；UI 的 S3_BASE 指向它
mkdir -p "$STATE_DIR"

step_done() { [ -f "$STATE" ] && python3 -c "
import json,sys; print('yes' if json.load(open('$STATE')).get('$1') else 'no')" | grep -q yes; }
mark_done() { python3 -c "
import json,os
p='$STATE'; d=json.load(open(p)) if os.path.exists(p) else {}
d['$1']=True; json.dump(d,open(p,'w'),indent=1)"; }

notify() {  # notify <emoji+text>（webhook 缺就跳過；雙態都發）
  # 走 manage.py shell 取 settings（與 statscheck 同路）——cwd 底下的 django/
  # 專案目錄會遮蔽同名套件，直接 import django 必炸（2026-08-31 實踩，通知
  # 因此靜默跳過了一整輪出貨）
  NOTIFY_TEXT="$1" poetry run python django/manage.py shell -c '
import os, requests
from django.conf import settings
hook = getattr(settings, "SLACK_WEBHOOK_URL", "") or os.environ.get("SLACK_WEBHOOK_URL", "")
if not hook:
    print("(no SLACK_WEBHOOK_URL, notify skipped)")
else:
    requests.post(hook, json={"blocks": [{"type": "section", "text": {
        "type": "mrkdwn", "text": os.environ["NOTIFY_TEXT"]}}]}, timeout=10).raise_for_status()
' || echo '(slack notify skipped)'
}

echo "=== publish $YM (resume=$RESUME dry-run=$DRYRUN) ==="
[ -f "$RAW_ZIP" ] || { echo "!!! 找不到 $RAW_ZIP（export -p 跑了嗎？）"; exit 1; }

# --- 1. 聚合（check.sh 先跑 raw：驗 counts ＋注入編碼表——dedup-single 需要
# 編碼表已在 zip 內，故「驗 raw →聚合→驗 dedup」而非文件原寫的聚合全先）---
if ! step_done agg; then
  echo '----- 1. aggregate -----'
  # check.sh 在「呼叫者 cwd」解壓＋rm -rf tw-rental-data/——必須讓它在自己的
  # 目錄跑（那裡也才有編碼表/），否則會掃掉 cwd 下的同名目錄（2026-08-30 實踩）
  ( cd "$AGG" && ./check.sh "$OLDPWD/$RAW_ZIP" ) | tail -6
  "$AGG/dedup-single.sh" "$(pwd)/$RAW_ZIP" || exit 1
  # dedup-single 產物落在 csv-aggregator/ 同層或 zip 同目錄，統一移回 datas/
  [ -f "$AGG/[${YM}][CSV][Deduplicated] TW-Rental-Data.zip" ] && \
    mv "$AGG/[${YM}][CSV][Deduplicated] TW-Rental-Data.zip" "$DEDUP_ZIP"
  [ -f "$DEDUP_ZIP" ] || { echo '!!! dedup 產物不見了'; exit 1; }
  if [[ "$MONTH" =~ ^(03|06|09|12)$ ]]; then
    Q=$(( (10#$MONTH - 1) / 3 + 1 ))
    QDIR=$(mktemp -d)
    ok=1
    for m in $(seq $(( (Q-1)*3 + 1 )) $(( Q*3 ))); do
      mz="$DATAS/[$YEAR$(printf %02d $m)][CSV][Raw] TW-Rental-Data.zip"
      [ -f "$mz" ] && cp "$mz" "$QDIR/" || ok=0
    done
    if [ $ok = 1 ]; then
      "$AGG/merge-and-dedup.sh" "$QDIR" "${YEAR}Q${Q}" || exit 1
      mv "$AGG/[${YEAR}Q${Q}]"*.zip "$DATAS/" 2>/dev/null || true
    else
      echo "!!! 季度聚合跳過：該季月 zip 不齊（缺月照紅色分支敘事處理）"
    fi
    rm -rf "$QDIR"
  fi
  mark_done agg
fi

# --- 2. 驗證（quality gate）---
VERDICT=green
if ! step_done verify; then
  echo '----- 2. verify -----'
  ( cd "$AGG" && ./check.sh "$OLDPWD/$DEDUP_ZIP" ) | tail -8
  mark_done verify
fi
poetry run python django/manage.py monthreport --month "$YM" -o "$STATE_DIR" \
  && VERDICT=green || { [ $? -eq 2 ] && VERDICT=red || exit 1; }
echo "gate verdict: $VERDICT"

# --- 紅色分岔：首跑即停，敘事完成後 --resume 續跑 ---
if [ "$VERDICT" = red ] && [ "$RESUME" = 0 ]; then
  [ "$DRYRUN" = 0 ] && notify "⚠️ *${YM} 出貨 gate 紅燈*（見 ${STATE_DIR}/${YM}.report.json）
人工三件事：data-issue blog 文、quality-issues.ts 條目、決定 quality_issue id
補完後：\`./publish.sh ${YM} --resume --quality-issue <id>\`"
  echo '=== 紅燈：停在敘事關卡（人工補完後 --resume）==='
  exit 2
fi
if [ "$VERDICT" = red ] && [ -z "$QISSUE" ]; then
  echo '!!! 紅月 --resume 需帶 --quality-issue <id>（拍板：quality_issue 永遠人工給值）'
  exit 1
fi

# --- 3. 上傳 S3 ---
if ! step_done upload; then
  echo '----- 3. upload -----'
  S3CP=(aws --profile twrh s3 cp)
  [ "$DRYRUN" = 1 ] && S3CP+=(--dryrun)
  for z in "$RAW_ZIP" "$DEDUP_ZIP" "$JSON_ZIP"; do
    [ -f "$z" ] || continue
    "${S3CP[@]}" "$z" "s3://$S3_BUCKET/$YEAR/$(basename "$z")" || exit 1
    if [ "$DRYRUN" = 0 ]; then
      remote=$(aws --profile twrh s3api head-object --bucket "$S3_BUCKET" \
        --key "$YEAR/$(basename "$z")" --query ContentLength --output text)
      local_size=$(stat -c%s "$z")
      [ "$remote" = "$local_size" ] || { echo "!!! size 不符 $z"; exit 1; }
    fi
  done
  [ "$DRYRUN" = 0 ] && mark_done upload
fi

# --- 4. UI 資料列 ---
if ! step_done ui; then
  echo '----- 4. ui stats -----'
  UI_ARGS=(--stats-dir ../ui-next/src/data/stats --year "$YEAR" \
           --period monthly --time "$((10#$MONTH))" \
           --zip "$RAW_ZIP" --zip "$DEDUP_ZIP")
  [ -f "$JSON_ZIP" ] && UI_ARGS+=(--json-zip "$JSON_ZIP")
  [ -n "$QISSUE" ] && UI_ARGS+=(--quality-issue "$QISSUE")
  [ -n "$COMMENT" ] && UI_ARGS+=(--comment "$COMMENT")
  poetry run python tools/publish_ui_stats.py "${UI_ARGS[@]}" || exit 1
  [ "$DRYRUN" = 0 ] && mark_done ui
fi

# --- 5. commit / push（紅綠都直 push——2026-08-31 拍板：紅月的 --resume 本身
# 就是人工確認，不再多卡一道 PR merge）---
echo '----- 5. ship -----'
STATS_JSON="../ui-next/src/data/stats/$YEAR.json"
SHIP_SHA=""
if [ "$DRYRUN" = 1 ]; then
  echo "(dry-run) would commit $STATS_JSON and push master"
else
  git -C .. add "ui-next/src/data/stats/$YEAR.json"
  if git -C .. diff --cached --quiet; then
    echo 'stats json 無變更，跳過 commit'
  else
    MSG="data: 發佈 $YM 月資料"
    [ "$VERDICT" = red ] && MSG="$MSG（quality_issue: $QISSUE）"
    git -C .. commit -m "$MSG"
    git -C .. push origin master
    SHIP_SHA=$(git -C .. rev-parse HEAD)
  fi
  mark_done ship
fi

# --- 通知（雙態都發，附可點連結）---
ICON=$([ "$VERDICT" = green ] && echo ✅ || echo ⚠️)
LINKS="<https://rentalhouse.g0v.ddio.io/download/|下載頁>｜<https://twrh.s3.ap-northeast-3.amazonaws.com/$YEAR/|S3>"
[ -n "$SHIP_SHA" ] && LINKS="<https://github.com/g0v/tw-rental-house-data/commit/$SHIP_SHA|commit ${SHIP_SHA:0:7}>｜$LINKS"
[ "$DRYRUN" = 0 ] && notify "$ICON *${YM} 已出貨*（$VERDICT$([ -n "$QISSUE" ] && echo "，quality_issue: $QISSUE")）
$LINKS"
echo "=== publish $YM done ($VERDICT) ==="
