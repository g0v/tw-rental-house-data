#!/usr/bin/env python
'''flow：make 式 pipeline runner（architecture-roadmap 3-2）。

四套編排（go.sh／orchestrate.sh／batch marker／progress 檔）收斂成
一份 stage 定義；本機與雲上同一條 DAG，差別只在 detail stage 的
executor（local＝行程內 batch 迴圈；ecs＝開 N 個 worker task 搶同一個
queue＋primary 陪跑）。完成判據＝artifact 存在（rawpack 日包、
manifest）或 stamp 檔（DB 型 stage，Phase 4 檔案化後逐一改 artifact）。

    poetry run python flow.py run [--date YYYY-MM-DD] [--from STAGE]
        [--executor local|ecs] [--append]
    poetry run python flow.py status [--date YYYY-MM-DD]

日期 pin（拍板）：--date 是唯一日期來源，flow 開場寫進 TWRH_TARGET_DATE
後所有 stage 繼承；--start-early 上移排程層——22:00 後的排程自己傳明日
date，flow 不看時鐘。（現制五處 env 讀點的「stage 收參數」全面替換，
隨 Phase 4 各 stage 檔案化時逐一收；env 傳遞在此前是唯一機制。）

過渡期定位：go.sh／orchestrate.sh 續為 production 路徑，flow 驗證
（一條指令從任一 stage 續跑，兩種 executor）後於部署日退役兩者。
breaker 偵測仍走 scrapy.log 字串（LOG_FILE 是 repo 層契約）；
log-grep 契約的退役需要 package 側配合，另案處理。
'''
import argparse
import glob
import gzip
import os
import shutil
import subprocess
import sys
from datetime import date as date_cls

BASE = os.path.dirname(os.path.realpath(__file__))
LOGS_DIR = os.path.join(BASE, '..', 'logs')


def flow_state_dir(date_str):
    root = os.environ.get(
        'TWRH_FLOW_STATE_DIR', os.path.join(LOGS_DIR, 'flow'))
    return os.path.join(root, date_str)


def read_env_file():
    '''.env 只有 scrapy／django 行程會讀（dotenv），flow 層自己補讀。'''
    path = os.path.join(BASE, '.env')
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())


class Ctx:
    def __init__(self, options):
        self.date = options.date
        self.executor = options.executor
        self.append = options.append
        self.stamp = os.environ.get('TWRH_LOG_STAMP') or \
            __import__('datetime').datetime.now().strftime('%Y.%m.%d.%H%M')
        self.seed_mode = os.environ.get('TWRH_DETAIL_SEED_MODE', 'full')
        self.refresh_days = os.environ.get('TWRH_DETAIL_REFRESH_DAYS', '7')

    def seed_mode_flags(self):
        if self.seed_mode == 'diff':
            return ['-a', 'seed_mode=diff',
                    '-a', 'refresh_days={}'.format(self.refresh_days)]
        return []


def run(cmd, **kwargs):
    print('+ {}'.format(' '.join(cmd)))
    return subprocess.run(cmd, cwd=BASE, **kwargs)


def manage(*args, check=True):
    return run(['poetry', 'run', 'python', 'django/manage.py', *args],
               check=check)


def archive_scrapy_log(ctx, name):
    src = os.path.join(BASE, 'scrapy.log')
    dst = os.path.join(LOGS_DIR, '{}.{}.log'.format(ctx.stamp, name))
    if os.path.exists(src):
        os.makedirs(LOGS_DIR, exist_ok=True)
        shutil.move(src, dst)
    return dst


def breaker_tripped(log_path):
    try:
        with open(log_path, errors='replace') as f:
            return any('error_rate_exceeded' in line for line in f)
    except OSError:
        return False


class StageFailed(Exception):
    pass


# --- stage bodies ---------------------------------------------------------

def stage_list(ctx):
    cmd = ['poetry', 'run', 'scrapy', 'crawl', 'list591', '-L', 'INFO']
    if ctx.append:
        cmd += ['-a', 'append=True']
    run(cmd, check=True)
    log = archive_scrapy_log(ctx, 'list')
    if breaker_tripped(log):
        raise StageFailed('list breaker tripped (error_rate_exceeded)')


def stage_seed(ctx):
    run(['poetry', 'run', 'scrapy', 'crawl', 'detail591', '-L', 'INFO',
         '-a', 'seed_only=True', *ctx.seed_mode_flags()], check=True)
    log = archive_scrapy_log(ctx, 'seed')
    with open(log, errors='replace') as f:
        if not any('seed-only mode' in line for line in f):
            raise StageFailed('seed generation failed')


def consume_loop(ctx, batch_size, extra_env=None):
    '''batch 迴圈（額滿由 spider touch stop marker 通知，dx 4-2）。'''
    import tempfile
    marker = tempfile.mktemp(prefix='twrh-batch-limit.')
    n = 1
    while True:
        if os.path.exists(marker):
            os.unlink(marker)
        env = {**os.environ, **(extra_env or {})}
        result = subprocess.run(
            ['poetry', 'run', 'scrapy', 'crawl', 'detail591', '-L', 'INFO',
             '-a', 'consume_only=True',
             '-a', 'batch_size={}'.format(batch_size),
             '-a', 'stop_marker={}'.format(marker)],
            cwd=BASE, env=env)
        if result.returncode != 0:
            raise StageFailed('detail batch {} exited {}'.format(
                n, result.returncode))
        log = archive_scrapy_log(ctx, 'detail.{}'.format(n))
        if breaker_tripped(log):
            raise StageFailed('detail breaker tripped at batch {}'.format(n))
        if not os.path.exists(marker):
            break
        n += 1
    if os.path.exists(marker):
        os.unlink(marker)


def stage_detail(ctx):
    if ctx.executor == 'local':
        consume_loop(ctx, os.environ.get('DETAIL_BATCH_SIZE', '2000'))
        return
    # ecs：開 N 個 consume-only worker（各自新公網 IP），primary 也陪跑
    # 消化 queue（套 worker 節流參數，見 orchestrate 08-31 首航教訓），
    # 最後等 worker 全停——「worker 全停」是唯一可靠收尾閘門
    arns = subprocess.run(
        ['poetry', 'run', 'python', 'devop/workers.py', 'launch'],
        cwd=BASE, capture_output=True, text=True, check=True).stdout.strip()
    if not arns:
        raise StageFailed('run-task returned no ARNs')
    print('workers: {}'.format(arns))
    consume_loop(
        ctx, os.environ.get('DETAIL_BATCH_SIZE', '10000'),
        extra_env={
            'TWRH_CONCURRENT_REQUESTS':
                os.environ.get('TWRH_WORKER_CONCURRENCY', '1'),
            'TWRH_DOWNLOAD_DELAY': os.environ.get('TWRH_WORKER_DELAY', '1'),
        })
    wait = run(['poetry', 'run', 'python', 'devop/workers.py',
                'wait', *arns.split()], check=False)
    if wait.returncode != 0:
        print('NOTE: worker wait timed out — data completeness suspect,'
              ' queuefinalize will tell')


def stage_deals(ctx):
    # #229：走「已成交」列表產成交事件，detail 之後、finalize 之前（queue
    # 的 DEAL 列一併對帳）。lookback 日跑 7 天（591 成交後數日仍補列）；回補時 TWRH_DEAL_LOOKBACK_DAYS 開大
    cmd = ['poetry', 'run', 'scrapy', 'crawl', 'deal591', '-L', 'INFO',
           '-a', 'lookback_days=' + os.environ.get('TWRH_DEAL_LOOKBACK_DAYS', '7')]
    if ctx.append:
        cmd += ['-a', 'append=True']
    run(cmd, check=True)
    log = archive_scrapy_log(ctx, 'deals')
    if breaker_tripped(log):
        raise StageFailed('deals breaker tripped (error_rate_exceeded)')


def stage_queuefinalize(_ctx):
    result = manage('queuefinalize', check=False)
    if result.returncode != 0:
        raise StageFailed('seeds != terminals — aborting pipeline')


def stage_rawpack(_ctx):
    result = manage('rawpack', '--reconcile', check=False)
    if result.returncode != 0:
        # 雙寫對帳期：DB 仍有 raw、scratch 保留可重打，警告不中止；
        # cutover（DB 停寫 raw）後升級為 StageFailed
        print('!!! rawpack failed — raw kept in scratch/DB, '
              'investigate before cutover')


def stage_synthts(ctx):
    if ctx.seed_mode == 'diff':
        manage('synthts')
    else:
        print('seed mode is full — synthts not needed')


def stage_sync(_ctx):
    manage('syncstateful', '-ts')


def stage_stats(_ctx):
    # 平行週的舊通道（statscheck＋distcheck）；切換日此 stage 整段退役
    manage('statscheck', check=False)
    manage('distcheck', check=False)


def stage_manifest(_ctx):
    manage('manifest')


def stage_quality(_ctx):
    # 紅＝告警＋非零 exit，但不擋 export（資料已入庫，出貨是月度 gate 的事）
    manage('qualitycheck', check=False)


def stage_export(_ctx):
    manage('export', '-p')


def stage_logs(ctx):
    for path in glob.glob(os.path.join(LOGS_DIR, '{}.*.log'.format(ctx.stamp))):
        with open(path, 'rb') as src, gzip.open(path + '.gz', 'wb') as dst:
            shutil.copyfileobj(src, dst)
        os.unlink(path)
    if os.environ.get('TWRH_CLUSTER'):
        run(['poetry', 'run', 'python', 'devop/workers.py',
             'ship_logs', LOGS_DIR, ctx.stamp], check=False)


# --- stage table（本機與雲上同一份定義） -----------------------------------

def manifest_artifacts(date_str):
    base = os.environ.get('TWRH_MANIFEST_DIR',
                          os.path.join(BASE, 'manifests'))
    return [os.path.join(base, date_str, stage + '.json')
            for stage in ('list', 'detail', 'deals', 'snapshot')]


def rawpack_artifacts(date_str):
    # 任一 vendor 的日包存在即視為完成；bucket 上傳後本地包會刪，
    # 以 stamp 檔補完成判據
    base = os.environ.get('TWRH_RAW_DIR', os.path.join(BASE, 'raws'))
    return glob.glob(os.path.join(base, '*', date_str + '.tar.zst'))


STAGES = [
    # (name, body, artifact_fn 或 None＝stamp 檔)
    ('list', stage_list, None),
    ('seed', stage_seed, None),
    ('detail', stage_detail, None),
    ('deals', stage_deals, None),
    ('queuefinalize', stage_queuefinalize, None),
    ('rawpack', stage_rawpack, rawpack_artifacts),
    ('synthts', stage_synthts, None),
    ('sync', stage_sync, None),
    ('stats', stage_stats, None),
    ('manifest', stage_manifest, manifest_artifacts),
    ('quality', stage_quality, None),
    ('export', stage_export, None),
    ('logs', stage_logs, None),
]
STAGE_NAMES = [name for name, _, _ in STAGES]


def stamp_path(date_str, name):
    return os.path.join(flow_state_dir(date_str), name + '.done')


def is_done(date_str, name, artifact_fn):
    if os.path.exists(stamp_path(date_str, name)):
        return True
    if artifact_fn:
        artifacts = artifact_fn(date_str)
        return bool(artifacts) and all(os.path.exists(p) for p in artifacts)
    return False


def mark_done(date_str, name):
    os.makedirs(flow_state_dir(date_str), exist_ok=True)
    with open(stamp_path(date_str, name), 'w'):
        pass


def cmd_run(options):
    ctx = Ctx(options)
    os.environ['TWRH_TARGET_DATE'] = ctx.date
    os.environ['TWRH_LOG_STAMP'] = ctx.stamp
    print('=== flow run {} (executor: {}, seed mode: {}) ==='.format(
        ctx.date, ctx.executor, ctx.seed_mode))

    start_index = 0
    if options.from_stage:
        start_index = STAGE_NAMES.index(options.from_stage)
        # --from：該 stage 起全部重跑（清 stamp）
        for name in STAGE_NAMES[start_index:]:
            try:
                os.unlink(stamp_path(ctx.date, name))
            except OSError:
                pass

    for index, (name, body, artifact_fn) in enumerate(STAGES):
        if index < start_index:
            print('----- {} (before --from, skip) -----'.format(name))
            continue
        forced = options.from_stage is not None and index >= start_index
        if not forced and is_done(ctx.date, name, artifact_fn):
            print('----- {} (done, skip) -----'.format(name))
            continue
        print('===== {} ====='.format(name.upper()))
        try:
            body(ctx)
        except StageFailed as err:
            print('!!! stage {} failed: {}'.format(name, err))
            stage_logs(ctx)
            sys.exit(1)
        except subprocess.CalledProcessError as err:
            print('!!! stage {} failed: {}'.format(name, err))
            stage_logs(ctx)
            sys.exit(1)
        mark_done(ctx.date, name)
    print('=== flow done ===')


def cmd_status(options):
    for name, _, artifact_fn in STAGES:
        state = 'done' if is_done(options.date, name, artifact_fn) else '-'
        print('{:14s} {}'.format(name, state))


def main():
    read_env_file()
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)

    run_parser = sub.add_parser('run', help='run the pipeline for a date')
    run_parser.add_argument('--date', default=date_cls.today().isoformat())
    run_parser.add_argument('--from', dest='from_stage', choices=STAGE_NAMES,
                            help='從這個 stage 起強制重跑')
    run_parser.add_argument('--executor', choices=['local', 'ecs'],
                            default='ecs' if os.environ.get('TWRH_CLUSTER')
                            else 'local')
    run_parser.add_argument('--append', action='store_true')

    status_parser = sub.add_parser('status', help='show stage completion')
    status_parser.add_argument('--date', default=date_cls.today().isoformat())

    options = parser.parse_args()
    if options.command == 'run':
        cmd_run(options)
    else:
        cmd_status(options)


if __name__ == '__main__':
    main()
