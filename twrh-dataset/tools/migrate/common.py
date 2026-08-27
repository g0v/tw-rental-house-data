"""遷移腳本共用件：目標 DB 連線、state marker、磁碟保險。

慣例：
- 來源 DB 走 Django default connection（本機 = twrh2025；M2 歷史段時改指舊 RDS）
- 目標 DB 走 TWRH_MIGRATE_TARGET_DSN（如 postgresql://postgres:pw@127.0.0.1:5432/twrh_new）
- 打包輸出目錄 TWRH_MIGRATE_WORK_DIR（M0 本機目錄扮演 S3；M3 換成上傳 S3 後刪本機檔）
- 所有 upsert 一律帶 updated 時間戳 guard——正確性由資料決定，批次重跑冪等
  （docs/aws-deployment-plan.md 開放問題 8）
"""
import json
import os
import shutil
import sys
import time

_DATASET_ROOT = os.path.realpath('{}/../..'.format(os.path.dirname(os.path.realpath(__file__))))
sys.path.append(_DATASET_ROOT)

DEFAULT_WORK_DIR = os.path.expanduser('~/src/twrh/migrate-work')
MIN_FREE_GB = float(os.environ.get('TWRH_MIGRATE_MIN_FREE_GB', '8'))


def load_django():
    # tools/utils.load_django 的相對路徑是 legacy（指向不存在的目錄），這裡自己來
    import django
    sys.path.append(os.path.join(_DATASET_ROOT, 'django'))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
    django.setup()


def source_cursor(name=None):
    """來源 DB cursor。name 給定時是 server-side cursor（大掃描不吃記憶體）。

    named cursor 需要 transaction（autocommit 下 psycopg2 直接報錯），
    用完呼叫 source_end_tx() 收尾。
    """
    from django.db import connection
    connection.ensure_connection()
    if name:
        conn = connection.connection
        if conn.autocommit:
            conn.autocommit = False
        else:
            # autocommit=False 下任何 plain query 都會默默開新 transaction，
            # 先收掉才能再開 named cursor
            conn.rollback()
        return conn.cursor(name=name)
    return connection.cursor()


def source_end_tx():
    from django.db import connection
    if connection.connection is not None and not connection.connection.autocommit:
        connection.connection.rollback()


def target_conn():
    import psycopg2
    dsn = os.environ.get('TWRH_MIGRATE_TARGET_DSN')
    if not dsn:
        sys.exit('TWRH_MIGRATE_TARGET_DSN not set, e.g. '
                 'postgresql://postgres:pw@127.0.0.1:5432/twrh_new')
    return psycopg2.connect(dsn)


def work_dir():
    d = os.environ.get('TWRH_MIGRATE_WORK_DIR', DEFAULT_WORK_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def check_disk(path=None):
    """ZFS pool 只剩 ~12%，灌爆前先停：低於 MIN_FREE_GB 就 abort。"""
    free_gb = shutil.disk_usage(path or work_dir()).free / 2**30
    if free_gb < MIN_FREE_GB:
        sys.exit(f'!!! free disk {free_gb:.1f} GB < {MIN_FREE_GB} GB, aborting '
                 '(clean packs or lower TWRH_MIGRATE_MIN_FREE_GB)')
    return free_gb


class State:
    """斷點續跑 marker，與 persist queue 同哲學：做完才記，沒記的重做。"""

    def __init__(self, name):
        self.path = os.path.join(work_dir(), f'{name}.state.json')
        self.data = {}
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = json.load(f)

    def done(self, key):
        return key in self.data

    def mark(self, key, **stats):
        self.data[key] = {'at': time.strftime('%F %T'), **stats}
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


def log(msg):
    print(f'[{time.strftime("%F %T")}] {msg}', flush=True)
