"""orchestrate.sh 的 worker 開啟／輪詢 helper（boto3，免在 image 裝 aws CLI）。

  python devop/workers.py launch          # 開 N 個 worker，印出 task ARN（空白分隔）
  python devop/workers.py wait ARN...     # 輪詢到全 STOPPED（exit 0）或逾時（exit 2）
  python devop/workers.py ship_logs DIR STAMP   # 該輪 *.gz 上 S3 logs/ 後刪本地檔

設定全走環境變數（見 orchestrate.sh 與 devop/aws/main.tf 的 crawler_env）。
worker＝同一 task def、consume-only、cpu/mem/速率以 run-task override 縮小。
"""
import glob
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
    # consume-only detail：batch 迴圈直到 queue 排空；log 以 hostname 區分留 EFS。
    # tail -F 把檔案 log 同步一份到 stdout → awslogs → CloudWatch（bash 收尾時
    # container 一併終結背景 tail，不必 kill）。
    log = '/data/logs/{}.worker-$(hostname).$n.log'.format(STAMP)
    return ('tail -F scrapy.log 2>/dev/null & '
            'n=1; while :; do poetry run scrapy crawl detail591 -L INFO '
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
            enableExecuteCommand=True,
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


def ship_logs(log_dir, stamp):
    # 本輪（stamp 開頭）的 .gz 上到 s3://$TWRH_RAW_BUCKET/logs/<date>/ 後刪本地檔
    # ——S3 是唯一長期留存（bucket lifecycle 30 天過期），EFS 不累積。
    # 單檔失敗不中斷 finalize，留在 EFS 等下輪重送。
    bucket = os.environ.get('TWRH_RAW_BUCKET')
    if not bucket:
        print('ship_logs: no TWRH_RAW_BUCKET, skipped', file=sys.stderr)
        return 0
    s3 = boto3.client('s3', region_name=REGION)
    date = TARGET_DATE or 'unknown'
    shipped = failed = 0
    for path in sorted(glob.glob(os.path.join(log_dir, stamp + '*.gz'))):
        key = 'logs/{}/{}'.format(date, os.path.basename(path))
        try:
            s3.upload_file(path, bucket, key)
            os.remove(path)
            shipped += 1
        except Exception as e:  # noqa: BLE001 — finalize 不因單檔炸掉
            print('ship_logs: {} failed: {}'.format(path, e), file=sys.stderr)
            failed += 1
    print('ship_logs: {} shipped to s3://{}/logs/{}/, {} failed'.format(
        shipped, bucket, date, failed), file=sys.stderr)
    return 1 if failed else 0


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: workers.py launch | wait ARN... | ship_logs DIR STAMP')
    if sys.argv[1] == 'launch':
        launch()
    elif sys.argv[1] == 'wait':
        sys.exit(wait(sys.argv[2:]))
    elif sys.argv[1] == 'ship_logs':
        sys.exit(ship_logs(sys.argv[2], sys.argv[3]))
    else:
        sys.exit('unknown subcommand: ' + sys.argv[1])


if __name__ == '__main__':
    main()
