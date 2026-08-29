"""orchestrate.sh 的 worker 開啟／輪詢 helper（boto3，免在 image 裝 aws CLI）。

  python devop/workers.py launch          # 開 N 個 worker，印出 task ARN（空白分隔）
  python devop/workers.py wait ARN...     # 輪詢到全 STOPPED（exit 0）或逾時（exit 2）

設定全走環境變數（見 orchestrate.sh 與 devop/aws/main.tf 的 crawler_env）。
worker＝同一 task def、consume-only、cpu/mem/速率以 run-task override 縮小。
"""
import os
import sys
import time

import boto3

REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')
CLUSTER = os.environ['TWRH_CLUSTER']
TASK_DEF = os.environ['TWRH_TASK_DEF']
SUBNETS = os.environ['TWRH_SUBNETS'].split(',')
SG = os.environ['TWRH_TASK_SG']
N = int(os.environ.get('TWRH_DETAIL_WORKERS', '1'))
WCPU = os.environ.get('TWRH_WORKER_CPU', '256')
WMEM = os.environ.get('TWRH_WORKER_MEMORY', '1024')
WCONC = os.environ.get('TWRH_WORKER_CONCURRENCY', '1')
WDELAY = os.environ.get('TWRH_WORKER_DELAY', '1')
BATCH = os.environ.get('DETAIL_BATCH_SIZE', '10000')
TARGET_DATE = os.environ.get('TWRH_TARGET_DATE', '')
STAMP = os.environ.get('TWRH_LOG_STAMP', 'run')
MAX_WAIT = int(os.environ.get('TWRH_MAX_WAIT_SEC', '25200'))

ecs = boto3.client('ecs', region_name=REGION)


def worker_command():
    # consume-only detail：batch 迴圈直到 queue 排空；log 以 hostname 區分留 EFS
    log = '/data/logs/{}.worker-$(hostname).$n.log'.format(STAMP)
    return ('n=1; while :; do poetry run scrapy crawl detail591 -L INFO '
            '-a consume_only=True -a batch_size={batch}; L={log}; '
            'mv scrapy.log $L 2>/dev/null || true; '
            "grep -q 'Batch limit reached' $L 2>/dev/null || break; "
            'n=$((n+1)); done').format(batch=BATCH, log=log)


def launch():
    env = [{'name': 'TWRH_CONCURRENT_REQUESTS', 'value': WCONC},
           {'name': 'TWRH_DOWNLOAD_DELAY', 'value': WDELAY}]
    if TARGET_DATE:
        env.append({'name': 'TWRH_TARGET_DATE', 'value': TARGET_DATE})
    arns = []
    remaining = N
    while remaining > 0:
        count = min(10, remaining)  # RunTask 單次上限 10
        resp = ecs.run_task(
            cluster=CLUSTER, taskDefinition=TASK_DEF, launchType='FARGATE',
            count=count, startedBy='orchestrate-{}'.format(STAMP)[:36],
            networkConfiguration={'awsvpcConfiguration': {
                'subnets': SUBNETS, 'securityGroups': [SG],
                'assignPublicIp': 'ENABLED'}},
            overrides={'cpu': WCPU, 'memory': WMEM, 'containerOverrides': [{
                'name': 'crawler', 'cpu': int(WCPU), 'memory': int(WMEM),
                'command': ['bash', '-c', worker_command()],
                'environment': env}]})
        arns += [t['taskArn'] for t in resp['tasks']]
        for f in resp.get('failures', []):
            print('run-task failure: {}'.format(f), file=sys.stderr)
        remaining -= count
    print(' '.join(arns))


def wait(arns):
    start = time.time()
    while True:
        # describe-tasks 單次上限 100 個 ARN；我們 N≤10 不分頁
        tasks = ecs.describe_tasks(cluster=CLUSTER, tasks=arns)['tasks']
        running = [t for t in tasks if t['lastStatus'] != 'STOPPED']
        if not running:
            print('all {} workers STOPPED'.format(len(arns)), file=sys.stderr)
            return 0
        if time.time() - start >= MAX_WAIT:
            print('!!! MAX_WAIT reached, {} still running'.format(len(running)),
                  file=sys.stderr)
            return 2
        print('  waiting: {}/{} running ({}m)'.format(
            len(running), len(arns), int((time.time() - start) / 60)),
            file=sys.stderr)
        time.sleep(120)


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: workers.py launch | wait ARN...')
    if sys.argv[1] == 'launch':
        launch()
    elif sys.argv[1] == 'wait':
        sys.exit(wait(sys.argv[2:]))
    else:
        sys.exit('unknown subcommand: ' + sys.argv[1])


if __name__ == '__main__':
    main()
