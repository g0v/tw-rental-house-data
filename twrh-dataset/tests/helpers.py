'''測試共用：暫存目錄＋環境變數、PersistQueue／response 工廠、twrhctl 指令執行、分區檔寫手。'''
import contextlib
import io
import json
import logging
import os
import shutil
import tempfile
import unittest
import warnings
from unittest import mock

import tests  # noqa: F401 — sys.path

ROOT_DIR = tests.ROOT   # twrh-dataset/

TEST_DATE = '2026-01-15'
YESTERDAY = '2026-01-14'
VENDOR_NAME = '591 租屋網'

# 會讓測試碰到網路或外部狀態的環境變數：一律清掉
_SCRUB = ('TWRH_WORKER_INDEX', 'TWRH_WORKER_COUNT', 'TWRH_QUEUE_SOURCE', 'TWRH_QUEUE_DB',
          'TWRH_QUEUE_MAX_ATTEMPTS', 'TWRH_QUEUE_DEAD_RATIO', 'SENTRY_DSN', 'SLACK_WEBHOOK_URL',
          'TWRH_CLUSTER', 'TWRH_SWEEP_WORKERS', 'TWRH_SWEEP_PAGES', 'TWRH_DEAL_LOOKBACK_DAYS',
          'TWRH_LATEST_BOOTSTRAP_FROM', 'TWRH_SNAPSHOT_REPLAY_DAYS', 'TWRH_DETAIL_SEED_MODE',
          'TWRH_LOG_STAMP', 'TWRH_FLOW_STATE_DIR', 'AWS_PROFILE')


class TempEnvTestCase(unittest.TestCase):
    '''每個測試一個暫存根目錄；artifacts／raws／manifests／progress 全指過去，日期釘 TEST_DATE。'''

    target_date = TEST_DATE

    def setUp(self):
        super().setUp()
        # rental.artifacts._zstd_lines 不關 Popen 的 stdout pipe（行為無害、只是 ResourceWarning 洗版）
        warnings.filterwarnings('ignore', category=ResourceWarning,
                                message=r'unclosed file <_io\.BufferedReader name=\d+>')
        self.tmp = tempfile.mkdtemp(prefix='twrh-test-')
        env = {
            'TWRH_ARTIFACT_DIR': os.path.join(self.tmp, 'artifacts'),
            'TWRH_RAW_SCRATCH_DIR': os.path.join(self.tmp, 'raws', 'scratch'),
            'TWRH_RAW_DIR': os.path.join(self.tmp, 'raws'),
            'TWRH_MANIFEST_DIR': os.path.join(self.tmp, 'manifests'),
            'TWRH_PROGRESS_DIR': os.path.join(self.tmp, 'progress'),
            'TWRH_TARGET_DATE': self.target_date,
            'TWRH_RAW_BUCKET': '',
            'TWRH_RUN_ID': 'run',
            'TWRH_RAW_SINK': '0',
        }
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        for key in _SCRUB:
            os.environ.pop(key, None)
        # detail 的 progress 檔寫在 repo 的 logs/progress（相對 persist_queue.py），導到暫存
        from crawler.spiders.persist_queue import PersistQueue
        progress_dir = os.path.join(self.tmp, 'progress')

        def progress_file_path(queue):
            return os.path.join(progress_dir, '{y}-{m:02d}-{d:02d}.detail.json'.format(**queue.ts))
        self._progress = mock.patch.object(PersistQueue, 'progress_file_path', progress_file_path)
        self._progress.start()

    def tearDown(self):
        while _OPEN_QUEUES:
            _OPEN_QUEUES.pop().close_files()
        self._progress.stop()
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()


_OPEN_QUEUES = []


def track(queue):
    '''測試結束時關掉 queue 的 append 檔（免 ResourceWarning）。'''
    _OPEN_QUEUES.append(queue)
    return queue


def make_queue(is_list=False, batch_size=0, parse_response=None, **kwargs):
    '''最小可用的 PersistQueue，不掛 spider（send_signal 為 no-op）。'''
    from crawler.spiders.persist_queue import PersistQueue
    return track(PersistQueue(
        vendor=VENDOR_NAME,
        is_list=is_list,
        logger=logging.getLogger('test'),
        seed_parser=lambda seed: seed,
        generate_request_args=lambda meta: {
            'url': 'https://example.com/{}'.format(meta.get('id', 'x')),
            'meta': {'rental': meta},
        },
        parse_response=parse_response or (lambda response: iter([True])),
        batch_size=batch_size,
        **kwargs
    ))


def worker_queue(index, count, **kwargs):
    with mock.patch.dict(os.environ, {'TWRH_WORKER_INDEX': str(index),
                                      'TWRH_WORKER_COUNT': str(count)}):
        return make_queue(**kwargs)


def drain(queue):
    '''認領到沒有為止，回傳 [QueueItem]。'''
    items = []
    while True:
        request = queue.next_request()
        if request is None:
            return items
        items.append(request.meta['db_request'])


def make_response(item, status=200, body=b'ok'):
    '''模擬 engine 回呼 parser_wrapper 時的 response（meta 掛 db_request＝QueueItem）。'''
    import scrapy
    from scrapy.http import TextResponse
    request = scrapy.Request(url='https://example.com/r',
                             meta={'rental': {'id': 'r'}, 'db_request': item})
    return TextResponse(url=request.url, status=status, body=body, request=request,
                        encoding='utf-8')


def terminals(type_name='detail', date_str=TEST_DATE, max_attempts=3):
    from rental import filequeue
    return filequeue.load_terminals('591', date_str, type_name, max_attempts)


def run_command(name, *argv):
    '''twrhctl 指令行程內執行：回 (exit code, stdout, stderr)。'''
    import importlib
    module = importlib.import_module('twrhctl.commands.' + name)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.Command().run_from_argv('twrhctl ' + name, list(argv))
    return code, out.getvalue(), err.getvalue()


def check_command(testcase, name, *argv):
    code, out, err = run_command(name, *argv)
    testcase.assertEqual(code, 0, '{} {} -> {}\n{}\n{}'.format(name, argv, code, out, err))
    return out


def write_shard(tree, rows, date_str=TEST_DATE, run='run'):
    from rental import artifacts
    with mock.patch.dict(os.environ, {'TWRH_RUN_ID': run}):
        writer = artifacts.ShardWriter(tree)
        for row in rows:
            writer.append({'vendor': '591', 'date': date_str, 'run': run, **row})
        writer.close()


def pack(testcase, tree, date_str=TEST_DATE):
    return check_command(testcase, 'artifactpack', '--tree', tree, '--date', date_str, '--no-upload')


def write_stubs(testcase, hids, date_str=TEST_DATE, run='run', seen_at=None, fingerprint=None):
    '''list stub 分區（打包好的）：hids 可為 id 或 (id, fingerprint)。'''
    from rental import tz
    at = (seen_at or tz.now()).isoformat()
    rows = []
    for h in hids:
        hid, fp = h if isinstance(h, tuple) else (h, fingerprint or 'fp-' + h)
        rows.append({'vendor_house_id': hid, 'seen_at': at, 'fingerprint': fp,
                     'monthly_price': 10000, 'stub_version': 1})
    write_shard('list', rows, date_str, run)
    pack(testcase, 'list', date_str)


def snapshot_row(hid, date_str, **kw):
    from rental import snapshot
    row = snapshot._blank('591', hid, date_str)
    row.update(kw)
    return row


def write_latest(rows, date_str=YESTERDAY):
    '''rows: {hid: {欄: 值}} → 總表 latest/<vendor>/daily/<date>.parquet。'''
    from rental import artifacts
    full = []
    for hid, extra in rows.items():
        row = snapshot_row(hid, date_str)
        row.pop('vendor_extra', None)
        row.update(extra)
        full.append(row)
    artifacts.write_latest(full, '591', date_str)


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
