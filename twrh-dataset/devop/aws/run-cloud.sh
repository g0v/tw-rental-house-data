#!/bin/bash
# 雲上一次性指令：用 crawler task def 起一個 task 跑任意 command，等它收工、印 log。
#   devop/aws/run-cloud.sh poetry run python django/manage.py rawpack --reconcile-only --full --date 2026-09-04
#   devop/aws/run-cloud.sh poetry run python flow.py run --date 2026-09-06 --from rawpack
#   devop/aws/run-cloud.sh poetry run python django/manage.py seedcheck --date 2026-09-10
# 一次只起一個（09-04 教訓：兩個 task 搶同一張 queue）；起前先確認沒有 crawler
# task 在跑（日跑／sweep），要爬站的指令另先暫停 sweep 排程。憑證：本機 twrh profile。
set -euo pipefail
PROFILE=${TWRH_AWS_PROFILE:-twrh}; REGION=${AWS_DEFAULT_REGION:-us-west-2}; CLUSTER=twrh
AWS=(aws --profile "$PROFILE" --region "$REGION")
[ $# -gt 0 ] || { echo "usage: $0 <command...>"; exit 2; }

RUNNING=$("${AWS[@]}" ecs list-tasks --cluster "$CLUSTER" --family twrh-crawler --desired-status RUNNING --query 'taskArns' --output text)
[ -z "$RUNNING" ] || { echo "!!! crawler task 已在跑：$RUNNING（等它停或 stop-task 後再來）"; exit 1; }

NET=$("${AWS[@]}" scheduler get-schedule --name twrh-daily-crawl --query 'Target.EcsParameters.NetworkConfiguration.awsvpcConfiguration' --output json)
SUBNET=$(echo "$NET" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Subnets"][0])')
SG=$(echo "$NET" | python3 -c 'import json,sys;print(json.load(sys.stdin)["SecurityGroups"][0])')
OVERRIDES=$(python3 -c 'import json,sys;print(json.dumps({"containerOverrides":[{"name":"crawler","command":sys.argv[1:]}]}))' "$@")

ARN=$("${AWS[@]}" ecs run-task --cluster "$CLUSTER" --task-definition twrh-crawler --launch-type FARGATE \
  --enable-execute-command \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --overrides "$OVERRIDES" --started-by run-cloud --query 'tasks[0].taskArn' --output text)
TID=${ARN##*/}
echo "task $TID started: $*"
until "${AWS[@]}" ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TID" 2>/dev/null; do :; done
EXIT=$("${AWS[@]}" ecs describe-tasks --cluster "$CLUSTER" --tasks "$TID" --query 'tasks[0].containers[0].exitCode' --output text)
"${AWS[@]}" logs get-log-events --log-group-name /twrh/crawler --log-stream-name "crawl/crawler/$TID" \
  --query 'events[].message' --output text | tr '\t' '\n' | tail -60
echo "task $TID exit $EXIT"
exit "$EXIT"
