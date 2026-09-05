#!/bin/bash
# 雲上出貨（publisher 雲化）：起一個 publisher task 跑 publish.sh，等它收工、印 log。
#   devop/aws/publish-cloud.sh                       # 出上個月（同排程）
#   devop/aws/publish-cloud.sh 202609 --dry-run      # 雲上演練
#   devop/aws/publish-cloud.sh 202609 --resume --quality-issue <id>   # 紅燈月補敘事後續跑
# 一次只起一個 task（09-04 教訓：連發兩個會搶同一份 state）。憑證：本機 twrh profile。
set -euo pipefail
PROFILE=${TWRH_AWS_PROFILE:-twrh}; REGION=${AWS_DEFAULT_REGION:-us-west-2}; CLUSTER=twrh
AWS=(aws --profile "$PROFILE" --region "$REGION")

RUNNING=$("${AWS[@]}" ecs list-tasks --cluster "$CLUSTER" --family twrh-publisher --desired-status RUNNING --query 'taskArns' --output text)
[ -z "$RUNNING" ] || { echo "!!! publisher task 已在跑：$RUNNING"; exit 1; }

NET=$("${AWS[@]}" scheduler get-schedule --name twrh-daily-crawl --query 'Target.EcsParameters.NetworkConfiguration.awsvpcConfiguration' --output json)
SUBNET=$(echo "$NET" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Subnets"][0])')
SG=$(echo "$NET" | python3 -c 'import json,sys;print(json.load(sys.stdin)["SecurityGroups"][0])')
CMD=$(python3 -c 'import json,sys;print(json.dumps(["./publish.sh"]+sys.argv[1:]))' "$@")
OVERRIDES=$(python3 -c 'import json,sys;print(json.dumps({"containerOverrides":[{"name":"publisher","command":json.loads(sys.argv[1])}]}))' "$CMD")

ARN=$("${AWS[@]}" ecs run-task --cluster "$CLUSTER" --task-definition twrh-publisher --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --overrides "$OVERRIDES" --started-by publish-cloud --query 'tasks[0].taskArn' --output text)
TID=${ARN##*/}
echo "task $TID started: ./publish.sh $*"
until "${AWS[@]}" ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TID" 2>/dev/null; do :; done
EXIT=$("${AWS[@]}" ecs describe-tasks --cluster "$CLUSTER" --tasks "$TID" --query 'tasks[0].containers[0].exitCode' --output text)
"${AWS[@]}" logs get-log-events --log-group-name /twrh/publisher --log-stream-name "publish/publisher/$TID" \
  --query 'events[].message' --output text | tr '\t' '\n' | tail -40
echo "task $TID exit $EXIT（2＝紅燈停在敘事關卡）"
exit "$EXIT"
