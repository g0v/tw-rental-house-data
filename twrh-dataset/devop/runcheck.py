"""雲上日跑驗收摘要（不進 container、不碰 RDS）：CloudWatch log ＋ S3 manifest。

  AWS_PROFILE=twrh python devop/runcheck.py [YYYY-MM-DD]     # 預設今天（台北）

印出：當前 RUNNING task、當日 orchestrate 主任務的 stage 時間軸與關鍵結果行
（list／seed／deals 進度、queuefinalize、rawpack、distcheck、qualitycheck、
非 fill-rate 的 ERROR 數）、S3 上四份 manifest 的重點數字與 raw 日包大小。
平行比對（statscheck Slack ✅ vs manifest）：拿這裡的 manifest 數字對 Slack。
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import boto3

REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')
CLUSTER = os.environ.get('TWRH_CLUSTER', 'twrh')
LOG_GROUP = os.environ.get('TWRH_LOG_GROUP', '/twrh/crawler')
BUCKET = os.environ.get('TWRH_RAW_BUCKET', 'twrh-w2')
TZ = timezone(timedelta(hours=8))

KEY_LINES = re.compile(
    r'^=====|^=== orchestrate|seeds \d+ = |零種子|seeds == terminals|'
    r'rawpack|reconcile|packed|distribution invariants|distcheck|'
    r'hard failure|all assertions|wrote manifests|error_rate|'
    r'diff seeds:|seed-only mode|\[deal\] \d+ events|\[deal\] seeding|'
    r'=== sweep|\[frontier\] \d+ unseen houses|sweep skipped|generatingrequest|'
    r'workers:|NOTE|Traceback|!!!|CommandError')
PROGRESS = re.compile(r'\[(list591|detail591|deal591)\] INFO: Batch: (\S+) \(')
DEAL_PAGE = re.compile(r'\[deal\] (\S+) page (\d+):')


def local(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, TZ)


def running_tasks(ecs):
    arns = ecs.list_tasks(cluster=CLUSTER, desiredStatus='RUNNING').get('taskArns', [])
    if not arns:
        return []
    tasks = ecs.describe_tasks(cluster=CLUSTER, tasks=arns)['tasks']
    return [(t['taskArn'].split('/')[-1][:12], t.get('startedBy', '?'),
             t.get('startedAt'), t['lastStatus']) for t in tasks]


def day_streams(logs, day):
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    lo, hi = start.timestamp() * 1000, (start + timedelta(days=1)).timestamp() * 1000
    out = []
    paginator = logs.get_paginator('describe_log_streams')
    for page in paginator.paginate(logGroupName=LOG_GROUP, orderBy='LastEventTime',
                                   descending=True, PaginationConfig={'MaxItems': 60}):
        for s in page['logStreams']:
            first = s.get('firstEventTimestamp')
            if first and lo <= first < hi:
                out.append(s)
    return out


def stream_events(logs, name):
    token = None
    while True:
        kwargs = {'logGroupName': LOG_GROUP, 'logStreamName': name, 'startFromHead': True}
        if token:
            kwargs['nextToken'] = token
        resp = logs.get_log_events(**kwargs)
        for e in resp['events']:
            yield e['timestamp'], e['message']
        if resp.get('nextForwardToken') == token:
            break
        token = resp.get('nextForwardToken')


def summarize_stream(logs, stream):
    name = stream['logStreamName']
    lines, last_progress, deal_pages, n_error, n_fillrate = [], {}, {}, 0, 0
    is_primary = False
    for ts, msg in stream_events(logs, name):
        if '=== orchestrate' in msg:
            is_primary = True
        if '=== sweep' in msg and not is_primary:
            is_primary = 'sweep'
        if KEY_LINES.search(msg):
            lines.append('{} {}'.format(local(ts).strftime('%H:%M:%S'), msg.strip()[:160]))
        m = PROGRESS.search(msg)
        if m:
            last_progress[m.group(1)] = (local(ts).strftime('%H:%M:%S'), m.group(2))
        m = DEAL_PAGE.search(msg)
        if m:
            deal_pages[m.group(1)] = int(m.group(2))
        if ' ERROR: ' in msg or 'ERROR' in msg[:40]:
            if '[fill-rate]' in msg:
                n_fillrate += 1
            else:
                n_error += 1
    return {
        'stream': name.split('/')[-1][:12], 'primary': is_primary,
        'first': local(stream['firstEventTimestamp']).strftime('%m-%d %H:%M'),
        'last': local(stream['lastEventTimestamp']).strftime('%m-%d %H:%M'),
        'lines': lines, 'progress': last_progress, 'deal_pages': deal_pages,
        'n_error': n_error, 'n_fillrate_error': n_fillrate,
    }


def manifest(s3, day, stage):
    key = 'manifests/{}/{}.json'.format(day.isoformat(), stage)
    try:
        body = s3.get_object(Bucket=BUCKET, Key=key)['Body'].read()
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def raw_pack(s3, day):
    key = 'raw/591/{}.tar.zst'.format(day.isoformat())
    try:
        head = s3.head_object(Bucket=BUCKET, Key=key)
        return '{:.1f} MB'.format(head['ContentLength'] / 1e6)
    except Exception:
        return None


def main():
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(TZ).date()
    session = boto3.session.Session(region_name=REGION)
    ecs, logs, s3 = session.client('ecs'), session.client('logs'), session.client('s3')

    print('== {} 驗收摘要（{} 產生）'.format(day, datetime.now(TZ).strftime('%m-%d %H:%M')))
    print('-- RUNNING tasks:')
    for tid, by, started, status in running_tasks(ecs) or []:
        print('   {} startedBy={} since={} {}'.format(
            tid, by, started.astimezone(TZ).strftime('%H:%M') if started else '?', status))
    if not running_tasks(ecs):
        print('   （無）')

    print('-- 當日 log streams:')
    streams = day_streams(logs, day)
    if not streams:
        print('   （尚無）')
    summaries = [summarize_stream(logs, s) for s in streams]
    for s in sorted(summaries, key=lambda x: (not x['primary'], x['first'])):
        tag = ('PRIMARY' if s['primary'] is True else
               'SWEEP' if s['primary'] == 'sweep' else 'worker/one-off')
        print('   {} {} {}→{} errors={} fill-rate-errors={}'.format(
            s['stream'], tag, s['first'], s['last'], s['n_error'], s['n_fillrate_error']))
        if s['primary']:
            for line in s['lines']:
                print('      ' + line)
            for spider, (t, prog) in s['progress'].items():
                print('      progress {} {} {}'.format(spider, t, prog))
            if s['deal_pages']:
                print('      deals pages: {}'.format(
                    ', '.join('{} {}'.format(c, p) for c, p in sorted(s['deal_pages'].items()))))

    print('-- S3 manifests/{}:'.format(day))
    for stage in ('list', 'detail', 'deals', 'snapshot'):
        m = manifest(s3, day, stage)
        if not m:
            print('   {}: （無）'.format(stage))
            continue
        q = m.get('queue') or {}
        parts = ['source={}'.format(m.get('source'))]
        if q:
            parts.append('queue seeds={} done={} dead={} residue={}'.format(
                q.get('seeds'), q.get('done'), q.get('dead'), q.get('residue')))
        parts.append('counts={}'.format(json.dumps(m.get('counts', {}), ensure_ascii=False)))
        if stage == 'list':
            parts.append('capture={}'.format(json.dumps(m.get('capture', {}))))
        if stage == 'deals':
            parts.append('by_deal_date={}'.format(json.dumps(m.get('by_deal_date', {}))))
            parts.append('median_n_day_deal={}'.format((m.get('dist') or {}).get('median_n_day_deal')))
        print('   {}: {}'.format(stage, ' | '.join(parts)))
    print('-- raw 日包 raw/591/{}.tar.zst: {}'.format(day, raw_pack(s3, day) or '（無）'))


if __name__ == '__main__':
    main()
