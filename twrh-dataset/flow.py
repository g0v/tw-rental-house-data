#!/usr/bin/env python
'''flow：make 式 pipeline runner（architecture-roadmap 3-2；D6b 起唯一編排）。

一份 stage 定義，本機與雲上同一條 DAG，差別只在 detail stage 的 executor
（local＝行程內 batch 迴圈；ecs＝開 N 個 worker task 搶同一個 queue＋
primary 陪跑）。完成判據＝artifact 存在（rawpack 日包、manifest）或
stamp 檔（DB 型 stage，Phase 4 檔案化後逐一改 artifact）。

    poetry run python flow.py run   [--date YYYY-MM-DD] [--from STAGE]
        [--executor local|ecs] [--append] [--vendor 591] [--dry-run]
    poetry run python flow.py sweep [--date YYYY-MM-DD] [--vendor 591] [--dry-run]
    poetry run python flow.py status [--date YYYY-MM-DD]

`run`＝日跑（每月 1 日第一個 stage 先出上月 export）；`sweep`＝前緣掃描
（白天每數小時：list 前緣 → 新物件 detail → 對帳 → 日包聯集），同一天多
次 run，各自的 stamp 落在 `logs/flow/<date>/sweep-<HHMM>/`。起跑先問
queuebusy：同 vendor 同日 bucket 有人在爬就讓路（exit 0，不告警）。

vendor 維度（multi-vendor-plan〈營運政策層〉）：spider 名、要不要跑
deals／sweep、頁數、lookback、sweep 速率都從 `crawler/vendor_profiles.py`
的 profile 取，flow 本身不認識 591。

日期 pin（拍板）：--date 是唯一日期來源，flow 開場寫進 TWRH_TARGET_DATE
後所有 stage 繼承；--start-early 上移排程層——22:00 後的排程自己傳明日
date，flow 不看時鐘。breaker 偵測仍走 scrapy.log 字串（LOG_FILE 是 repo
層契約）；log-grep 契約的退役需要 package 側配合，另案處理。
'''
import argparse
import glob
import gzip
import os
import shutil
import subprocess
import sys
from datetime import date as date_cls, datetime

BASE = os.path.dirname(os.path.realpath(__file__))
LOGS_DIR = os.path.join(BASE, '..', 'logs')
sys.path.insert(0, BASE)
from crawler import vendor_profiles  # noqa: E402

DRY_RUN = False


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
    def __init__(self, options, kind='run'):
        self.kind = kind
        self.date = options.date
        self.vendor = vendor_profiles.get(options.vendor)
        self.executor = getattr(options, 'executor', 'local')
        self.append = getattr(options, 'append', False)
        now = datetime.now()
        if kind == 'sweep':
            # 同一天多次 run：stamp 帶時分，stamp 檔各自一個目錄
            self.run_id = 'sweep-' + now.strftime('%H%M')
            self.stamp = os.environ.get('TWRH_LOG_STAMP') or \
                now.strftime('%Y.%m.%d.%H%M') + '.sweep'
            self.state_dir = os.path.join(flow_state_dir(self.date), self.run_id)
        else:
            self.run_id = 'run'
            self.stamp = os.environ.get('TWRH_LOG_STAMP') or \
                now.strftime('%Y.%m.%d.%H%M')
            self.state_dir = flow_state_dir(self.date)
        self.seed_mode = os.environ.get('TWRH_DETAIL_SEED_MODE', 'full')
        self.refresh_days = os.environ.get('TWRH_DETAIL_REFRESH_DAYS', '7')

    def seed_mode_flags(self):
        if self.seed_mode == 'diff':
            return ['-a', 'seed_mode=diff',
                    '-a', 'refresh_days={}'.format(self.refresh_days)]
        return []

    def crawl(self, spider, *args):
        cmd = ['poetry', 'run', 'scrapy', 'crawl', spider, '-L', 'INFO', *args]
        if self.append:
            cmd += ['-a', 'append=True']
        return cmd


def run(cmd, **kwargs):
    print('+ {}'.format(' '.join(cmd)))
    if DRY_RUN:
        return subprocess.CompletedProcess(cmd, 0, '', '')
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


class SweepYield(Exception):
    '''互斥讓路：不是失敗，exit 0、下一輪再來。'''


# --- 日跑 stage bodies -------------------------------------------------------

def stage_list(ctx):
    run(ctx.crawl(ctx.vendor.list_spider), check=True)
    log = archive_scrapy_log(ctx, 'list')
    if breaker_tripped(log):
        raise StageFailed('list breaker tripped (error_rate_exceeded)')


def stage_seed(ctx):
    run(ctx.crawl(ctx.vendor.detail_spider, '-a', 'seed_only=True',
                  *ctx.seed_mode_flags()), check=True)
    log = archive_scrapy_log(ctx, 'seed')
    if DRY_RUN:
        return
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
        cmd = ctx.crawl(ctx.vendor.detail_spider,
                        '-a', 'consume_only=True',
                        '-a', 'batch_size={}'.format(batch_size),
                        '-a', 'stop_marker={}'.format(marker))
        print('+ {}'.format(' '.join(cmd)))
        if DRY_RUN:
            return
        result = subprocess.run(cmd, cwd=BASE, env=env)
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
    launch = run(['poetry', 'run', 'python', 'devop/workers.py', 'launch'],
                 capture_output=True, text=True, check=True)
    arns = (launch.stdout or '').strip()
    if not arns and not DRY_RUN:
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
    # 的 DEAL 列一併對帳）。profile 決定這個 vendor 有沒有這個 stage
    if not ctx.vendor.has_deals_stage:
        print('vendor {} has no deals stage — skip'.format(ctx.vendor.short))
        return
    run(ctx.crawl(ctx.vendor.deal_spider,
                  '-a', 'lookback_days=' + str(ctx.vendor.deal_lookback_days)),
        check=True)
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
        # D5 後日包是 raw 唯一去向：硬紅（scratch 保留，修好 --from rawpack）
        raise StageFailed('rawpack failed — DB no longer keeps raw, '
                          'scratch retained; fix and rerun --from rawpack')


def _artifactpack(tree):
    # 4a／4b 雙寫期：DB 仍是真相，分區檔失敗（例如 S3 權限未到位）只
    # 大聲警告不中止；本地分區檔／scratch 都留著，補跑 artifactpack 即可
    result = manage('artifactpack', '--tree', tree, check=False)
    if result.returncode != 0:
        print('!!! artifactpack --tree {} failed (advisory during dual-write; '
              'scratch/local partition retained)'.format(tree))


def stage_filequeuecheck(_ctx):
    # 4e 雙軌：檔案 queue 記帳對 request_ts；advisory
    manage('filequeuecheck', check=False)


def stage_liststubs(_ctx):
    # 4a：本輪 list stub shards → list/<vendor>/<date>/<run>.jsonl.zst（＋S3）
    _artifactpack('list')


def stage_seedcheck(_ctx):
    # 4a 驗收：純函數從 stub 重算 seeds 對 queue；advisory，不擋 pipeline
    manage('seedcheck', check=False)


def stage_parsed(_ctx):
    # 4b：本輪 parsed shards → parsed/<vendor>/<date>/<run>.parquet（＋S3）
    _artifactpack('parsed')


def stage_parsedcheck(_ctx):
    # 4b 驗收：當日 parquet 逐欄對 HouseTS；advisory（雙寫期 DB 是真相）
    manage('parsedcheck', check=False)


def stage_synthts(ctx):
    if ctx.seed_mode == 'diff':
        manage('synthts')
    else:
        print('seed mode is full — synthts not needed')


def stage_sync(_ctx):
    manage('syncstateful', '-ts')


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


# --- 前緣掃描 stage bodies（devop/sweep.sh 退役，2026-09-07）-------------------

def sweep_env(ctx):
    # 保守速率：白天與使用者共用站方資源；sweep 試跑（09-05）在 1,500 筆全速
    # detail 後吃到連續 403——比主跑的速率參數更溫和
    return {
        'TWRH_CONCURRENT_REQUESTS': str(ctx.vendor.sweep_concurrency),
        'TWRH_DOWNLOAD_DELAY': str(ctx.vendor.sweep_delay),
    }


def stage_busy(ctx):
    # 互斥：同 vendor 同日期 bucket，別人（拖長的日跑、臨時 run-task）正在爬
    # 就讓路。以「N 小時內更新過的 in_flight 列」判定，避免被 SIGKILL 殘留
    # 的舊 in_flight 永久擋住
    result = manage('queuebusy', '--vendor', ctx.vendor.name,
                    '--hours', str(ctx.vendor.busy_window_hours), check=False)
    if result.returncode != 0:
        raise SweepYield('another crawl is in flight on this queue')


def stage_frontier(ctx):
    if not ctx.vendor.supports_frontier:
        raise SweepYield('vendor {} does not support frontier sweep'.format(
            ctx.vendor.short))
    os.environ.update(sweep_env(ctx))
    run(ctx.crawl(ctx.vendor.list_spider,
                  '-a', 'frontier_pages={}'.format(ctx.vendor.frontier_pages)),
        check=True)
    log = archive_scrapy_log(ctx, 'sweep-list')
    if breaker_tripped(log):
        raise StageFailed('sweep list breaker tripped')
    if not DRY_RUN:
        with open(log, errors='replace') as f:
            for line in f:
                if 'unseen houses discovered' in line:
                    print(line.strip().split('INFO: ')[-1])


def stage_newdetail(ctx):
    os.environ.update(sweep_env(ctx))
    # 兩趟：第二趟只撿第一趟 failed 的重試（seed_mode=new 不重排當日已有列的物件）
    for n in range(1, int(ctx.vendor.sweep_detail_passes) + 1):
        run(ctx.crawl(ctx.vendor.detail_spider, '-a', 'seed_mode=new'), check=True)
        log = archive_scrapy_log(ctx, 'sweep-detail.{}'.format(n))
        if breaker_tripped(log):
            raise StageFailed('sweep detail breaker tripped at pass {}'.format(n))


def stage_sweep_finalize(_ctx):
    # 同日 queue 一併對帳（含清晨那輪）；紅＝本輪殘留，Slack 有訊息。
    # 終結列清理留給日跑
    result = manage('queuefinalize', '--no-cleanup', check=False)
    if result.returncode != 0:
        raise StageFailed('seeds != terminals')


# --- stage tables（本機與雲上同一份定義） ------------------------------------

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


RUN_STAGES = [
    # (name, body, artifact_fn 或 None＝stamp 檔)
    # export 排最前：每月 1 日出上月（export -p 自判），此刻 DB＝上月最後一天
    # 23:00 sweep 後的狀態，當日爬取尚未動到任何列（2026-09-07 拍板）
    ('export', stage_export, None),
    ('list', stage_list, None),
    ('liststubs', stage_liststubs, None),
    ('seed', stage_seed, None),
    ('seedcheck', stage_seedcheck, None),
    ('detail', stage_detail, None),
    ('deals', stage_deals, None),
    ('queuefinalize', stage_queuefinalize, None),
    ('filequeuecheck', stage_filequeuecheck, None),
    ('rawpack', stage_rawpack, rawpack_artifacts),
    ('parsed', stage_parsed, None),
    ('parsedcheck', stage_parsedcheck, None),
    ('synthts', stage_synthts, None),
    ('sync', stage_sync, None),
    ('manifest', stage_manifest, manifest_artifacts),
    ('quality', stage_quality, None),
    ('logs', stage_logs, None),
]
RUN_STAGE_NAMES = [name for name, _, _ in RUN_STAGES]

SWEEP_STAGES = [
    ('busy', stage_busy, None),
    ('frontier', stage_frontier, None),
    ('liststubs', stage_liststubs, None),
    ('newdetail', stage_newdetail, None),
    ('queuefinalize', stage_sweep_finalize, None),
    ('filequeuecheck', stage_filequeuecheck, None),
    # 本輪 raw 併進當日日包（rawpack 合併既有包＋scratch，同日多次 run＝聯集）
    ('rawpack', stage_rawpack, None),
    # 4a／4b 分區檔是一輪一檔，不聯集
    ('parsed', stage_parsed, None),
    ('logs', stage_logs, None),
]
SWEEP_STAGE_NAMES = [name for name, _, _ in SWEEP_STAGES]

# 相容：外部（tests／tools）仍可用舊名
STAGES = RUN_STAGES
STAGE_NAMES = RUN_STAGE_NAMES


def stamp_path(state_dir, name):
    return os.path.join(state_dir, name + '.done')


def is_done(ctx, name, artifact_fn):
    if os.path.exists(stamp_path(ctx.state_dir, name)):
        return True
    if artifact_fn:
        artifacts = artifact_fn(ctx.date)
        return bool(artifacts) and all(os.path.exists(p) for p in artifacts)
    return False


def mark_done(ctx, name):
    if DRY_RUN:
        return
    os.makedirs(ctx.state_dir, exist_ok=True)
    with open(stamp_path(ctx.state_dir, name), 'w'):
        pass


def run_stages(ctx, stages, from_stage=None):
    names = [name for name, _, _ in stages]
    start_index = 0
    if from_stage:
        start_index = names.index(from_stage)
        # --from：該 stage 起全部重跑（清 stamp）
        for name in names[start_index:]:
            try:
                os.unlink(stamp_path(ctx.state_dir, name))
            except OSError:
                pass
    for index, (name, body, artifact_fn) in enumerate(stages):
        if index < start_index:
            print('----- {} (before --from, skip) -----'.format(name))
            continue
        forced = from_stage is not None and index >= start_index
        if not forced and is_done(ctx, name, artifact_fn):
            print('----- {} (done, skip) -----'.format(name))
            continue
        print('===== {} ====='.format(name.upper()))
        try:
            body(ctx)
        except SweepYield as why:
            print('=== {} yielded: {} ==='.format(ctx.kind, why))
            return 0
        except StageFailed as err:
            print('!!! stage {} failed: {}'.format(name, err))
            if name != 'logs':
                stage_logs(ctx)
            return 1
        except subprocess.CalledProcessError as err:
            print('!!! stage {} failed: {}'.format(name, err))
            if name != 'logs':
                stage_logs(ctx)
            return 1
        mark_done(ctx, name)
    return 0


def cmd_run(options):
    ctx = Ctx(options, 'run')
    os.environ['TWRH_TARGET_DATE'] = ctx.date
    os.environ['TWRH_LOG_STAMP'] = ctx.stamp
    os.environ['TWRH_RUN_ID'] = ctx.run_id
    print('=== flow run {} (vendor: {}, executor: {}, seed mode: {}) ==='.format(
        ctx.date, ctx.vendor.short, ctx.executor, ctx.seed_mode))
    code = run_stages(ctx, RUN_STAGES, options.from_stage)
    if code == 0:
        print('=== flow done ===')
    sys.exit(code)


def cmd_sweep(options):
    ctx = Ctx(options, 'sweep')
    os.environ['TWRH_TARGET_DATE'] = ctx.date
    os.environ['TWRH_LOG_STAMP'] = ctx.stamp
    os.environ['TWRH_RUN_ID'] = ctx.run_id
    print('=== flow sweep {} {} (vendor: {}, frontier pages<={}) ==='.format(
        ctx.date, ctx.run_id, ctx.vendor.short, ctx.vendor.frontier_pages))
    code = run_stages(ctx, SWEEP_STAGES, None)
    if code == 0:
        print('=== flow sweep {} done ==='.format(ctx.run_id))
    sys.exit(code)


def cmd_status(options):
    class _Opts:
        date = options.date
        vendor = options.vendor
    ctx = Ctx(_Opts, 'run')
    for name, _, artifact_fn in RUN_STAGES:
        state = 'done' if is_done(ctx, name, artifact_fn) else '-'
        print('{:14s} {}'.format(name, state))
    root = flow_state_dir(options.date)
    if os.path.isdir(root):
        sweeps = sorted(d for d in os.listdir(root) if d.startswith('sweep-'))
        for d in sweeps:
            done = sorted(f[:-5] for f in os.listdir(os.path.join(root, d))
                          if f.endswith('.done'))
            print('{:14s} {}'.format(d, ' '.join(done) or '-'))


def main():
    global DRY_RUN
    try:
        sys.stdout.reconfigure(line_buffering=True)   # CloudWatch 要看得到 stage 起訖
    except AttributeError:
        pass
    read_env_file()
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)

    def common(p):
        p.add_argument('--date', default=date_cls.today().isoformat())
        p.add_argument('--vendor', default='591', choices=vendor_profiles.names())
        p.add_argument('--dry-run', action='store_true',
                       help='只印指令不執行（不寫 stamp）')

    run_parser = sub.add_parser('run', help='日跑：從任一 stage 續跑整條 pipeline')
    common(run_parser)
    run_parser.add_argument('--from', dest='from_stage', choices=RUN_STAGE_NAMES,
                            help='從這個 stage 起強制重跑')
    run_parser.add_argument('--executor', choices=['local', 'ecs'],
                            default='ecs' if os.environ.get('TWRH_CLUSTER')
                            else 'local')
    run_parser.add_argument('--append', action='store_true')

    sweep_parser = sub.add_parser('sweep', help='前緣掃描：list 前緣→新物件 detail→對帳→日包')
    common(sweep_parser)

    status_parser = sub.add_parser('status', help='show stage completion')
    status_parser.add_argument('--date', default=date_cls.today().isoformat())
    status_parser.add_argument('--vendor', default='591')

    options = parser.parse_args()
    DRY_RUN = getattr(options, 'dry_run', False)
    if options.command == 'run':
        cmd_run(options)
    elif options.command == 'sweep':
        cmd_sweep(options)
    else:
        cmd_status(options)


if __name__ == '__main__':
    main()
