'''檔案分區的佈局與打包（Phase 4a／4b）。

樹（本機預設 twrh-dataset/artifacts；AWS 是 EFS /data/artifacts，
S3 同名前綴）：

    <artifact_dir>/scratch/<tree>/<vendor>/<date>/<run>.<host>.<pid>.jsonl   爬取行程直寫
    <artifact_dir>/list/<vendor>/<date>/<run>.jsonl.zst                       4a list stub
    <artifact_dir>/parsed/<vendor>/<date>/<run>.parquet                       4b parsed
    <artifact_dir>/deals/<vendor>/<date>/<run>.parquet                        4d deal events
    <artifact_dir>/snapshot/<vendor>/<date>.parquet                           4c snapshot（一天一檔）

一輪（flow run id：run／sweep-HHMM）一檔、**不做同日改寫**：sweep 每輪
自己的檔，讀取端 glob 整個日期目錄即當日全部。這是刻意與 rawpack
「同日聯集改寫日包」不同——避開覆蓋既有 S3 key 的整類事故
（2026-09-07）。同一 run 重跑（flow --from）才會與本地既有檔聯集。

寫入側：多 worker 各自 append 自己的 shard（單寫者、逐行 flush），
收尾 `manage.py artifactpack --tree list|parsed` 打成分區檔、上 S3、清
scratch。與 rental/raws.py 同理住在 django 樹（manage.py 行程看不到
crawler 套件）。
'''
import glob
import json
import os
import socket
import subprocess

from rental.raws import raw_dir, vendor_dirname  # noqa: F401
from rental import contracts

TREES = {
    'list': (contracts.LIST_STUB_FIELDS, 'jsonl.zst'),
    'parsed': (contracts.PARSED_FIELDS, 'parquet'),
    # 4d：deal591 成交事件，一輪一檔、事件全留（不去重）
    'deals': (contracts.DEAL_EVENT_FIELDS, 'parquet'),
}
# 4c：snapshot 不是 shard 打包而是摺疊產物——一天一檔 snapshot/<vendor>/<date>.parquet，
# 日跑先把昨日重摺成 final（輸入齊全）、再摺今日 provisional；final 覆寫 provisional
# 是這棵樹裡唯一刻意的同 key 覆寫（bucket 有 versioning）
SNAPSHOT_TREE = 'snapshot'


def artifact_dir():
    '''預設跟 raws 同層（TWRH_RAW_DIR=/data/raws → /data/artifacts），
    不必為它多一個部署層 env。'''
    return os.environ.get(
        'TWRH_ARTIFACT_DIR',
        os.path.join(os.path.dirname(os.path.normpath(raw_dir())), 'artifacts'))


def run_id():
    '''flow 設 TWRH_RUN_ID（run／sweep-HHMM）；flow 之外的手動 scrapy 為 manual。'''
    return os.environ.get('TWRH_RUN_ID', 'manual')


def scratch_base():
    return os.path.join(artifact_dir(), 'scratch')


def scratch_dir(tree, vendor_short, date_str):
    return os.path.join(scratch_base(), tree, vendor_short, date_str)


def day_dir(tree, vendor_short, date_str):
    return os.path.join(artifact_dir(), tree, vendor_short, date_str)


def partition_path(tree, vendor_short, date_str, run):
    return os.path.join(day_dir(tree, vendor_short, date_str),
                        '{}.{}'.format(run, TREES[tree][1]))


def s3_key(tree, vendor_short, date_str, run):
    return '{}/{}/{}/{}.{}'.format(tree, vendor_short, date_str, run, TREES[tree][1])


class ShardWriter:
    '''一個行程對一個 (tree, vendor, date) 的 append-only jsonl shard。'''

    def __init__(self, tree):
        self.tree = tree
        self._files = {}

    def _handle(self, vendor_short, date_str):
        key = (vendor_short, date_str)
        if key not in self._files:
            target = scratch_dir(self.tree, vendor_short, date_str)
            os.makedirs(target, exist_ok=True)
            name = '{}.{}.{}.jsonl'.format(run_id(), socket.gethostname(), os.getpid())
            self._files[key] = open(os.path.join(target, name), 'a', encoding='utf-8')
        return self._files[key]

    def append(self, row):
        f = self._handle(row['vendor'], row['date'])
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
        f.flush()

    def close(self):
        for f in self._files.values():
            f.close()
        self._files.clear()


# --- 讀 ---------------------------------------------------------------------

def _zstd_lines(path):
    proc = subprocess.Popen(['zstd', '-dcq', path], stdout=subprocess.PIPE)
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                yield json.loads(line)
    finally:
        if proc.wait() != 0:
            raise RuntimeError('zstd failed on {}'.format(path))


def partition_files(tree, vendor_short, date_str, bucket=None):
    '''當日所有 run 的分區檔（本地；沒有且給了 bucket 就從 S3 拉回）。'''
    ext = '*.' + TREES[tree][1]
    target = day_dir(tree, vendor_short, date_str)
    local = sorted(glob.glob(os.path.join(target, ext)))
    if local or not bucket:
        return local
    import boto3
    s3 = boto3.client('s3')
    prefix = '{}/{}/{}/'.format(tree, vendor_short, date_str)
    os.makedirs(target, exist_ok=True)
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            s3.download_file(bucket, obj['Key'],
                             os.path.join(target, os.path.basename(obj['Key'])))
    return sorted(glob.glob(os.path.join(target, ext)))


def list_partition_files(vendor_short, date_str, bucket=None):
    return partition_files('list', vendor_short, date_str, bucket)


def read_parquet_rows(tree, vendor_short, date_str, bucket=None):
    '''當日全部分區列（跨 run，list of dict；不含 scratch）。'''
    import pyarrow.parquet as pq
    rows = []
    for path in partition_files(tree, vendor_short, date_str, bucket):
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def read_parsed_rows(vendor_short, date_str, bucket=None):
    return read_parquet_rows('parsed', vendor_short, date_str, bucket)


def read_deal_events(vendor_short, date_str, bucket=None):
    return read_parquet_rows('deals', vendor_short, date_str, bucket)


# --- snapshot（4c）------------------------------------------------------------

def snapshot_path(vendor_short, date_str):
    return os.path.join(artifact_dir(), SNAPSHOT_TREE, vendor_short, date_str + '.parquet')


def snapshot_s3_key(vendor_short, date_str):
    return '{}/{}/{}.parquet'.format(SNAPSHOT_TREE, vendor_short, date_str)


def snapshot_exists(vendor_short, date_str, bucket=None):
    return _fetch_snapshot(vendor_short, date_str, bucket) is not None


def _fetch_snapshot(vendor_short, date_str, bucket=None):
    '''本地檔路徑；沒有且給了 bucket 就從 S3 拉回；都沒有回 None。'''
    path = snapshot_path(vendor_short, date_str)
    if os.path.exists(path):
        return path
    if not bucket:
        return None
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client('s3')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        s3.download_file(bucket, snapshot_s3_key(vendor_short, date_str), path)
    except ClientError as err:
        if err.response.get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise
    return path


def read_snapshot(vendor_short, date_str, bucket=None):
    '''某日 snapshot 列（list of dict）；不存在回 None（與空列表區分）。'''
    path = _fetch_snapshot(vendor_short, date_str, bucket)
    if path is None:
        return None
    import pyarrow.parquet as pq
    return pq.read_table(path).to_pylist()


def write_snapshot(rows, vendor_short, date_str):
    '''摺疊結果 → snapshot/<vendor>/<date>.parquet（tmp＋rename）。回傳 (path, n_rows)。'''
    import pyarrow as pa
    import pyarrow.parquet as pq
    fields = contracts.SNAPSHOT_FIELDS
    # 逐欄建 array、不先複製成第二份 dict 列表：10 萬列 × 60 欄在 2 GB task 裡
    # 要省著用（from_pylist 會多一份中間物）
    rows = sorted(rows, key=lambda r: r['vendor_house_id'])
    schema = contracts.arrow_schema(fields)
    columns = []
    for (name, kind), arrow_field in zip(fields, schema):
        columns.append(pa.array(
            [contracts.coerce_value(r.get(name), kind) for r in rows], type=arrow_field.type))
    n = len(rows)
    del rows
    path = snapshot_path(vendor_short, date_str)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    pq.write_table(pa.Table.from_arrays(columns, schema=schema), tmp, compression='zstd')
    os.replace(tmp, path)
    return path, n


def upload_snapshot(bucket, vendor_short, date_str, path):
    '''snapshot 上 S3；同 key 覆寫是設計內的（final 蓋 provisional），印出來讓 log 看得到。'''
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client('s3')
    key = snapshot_s3_key(vendor_short, date_str)
    try:
        s3.head_object(Bucket=bucket, Key=key)
        print('    NOTE overwriting existing s3://{}/{} (snapshot refold)'.format(bucket, key))
    except ClientError as err:
        if err.response.get('Error', {}).get('Code') not in ('404', 'NoSuchKey', 'NotFound'):
            raise
    s3.upload_file(path, bucket, key)
    print('    uploaded s3://{}/{}'.format(bucket, key))
    return key


def read_list_stubs(vendor_short, date_str, bucket=None):
    '''yield 當日全部 stub 列（跨 run，含 scratch 裡尚未打包的）。'''
    for path in list_partition_files(vendor_short, date_str, bucket):
        yield from _zstd_lines(path)
    for path in sorted(glob.glob(os.path.join(
            scratch_dir('list', vendor_short, date_str), '*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


# --- 打包 -------------------------------------------------------------------

def pending_jobs(tree, date_str):
    '''scratch 裡待打包的 (vendor, date, run) → [shard paths]；日期取 <= 目標日
    （早於目標日＝前一天沒打包成功的孤兒，一併處理，與 rawpack 同規則）。'''
    jobs = {}
    base = os.path.join(scratch_base(), tree)
    if not os.path.isdir(base):
        return jobs
    for vendor in sorted(os.listdir(base)):
        vdir = os.path.join(base, vendor)
        if not os.path.isdir(vdir):
            continue
        for day in sorted(os.listdir(vdir)):
            if day > date_str or not os.path.isdir(os.path.join(vdir, day)):
                continue
            for shard in sorted(glob.glob(os.path.join(vdir, day, '*.jsonl'))):
                run = os.path.basename(shard).split('.', 1)[0]
                jobs.setdefault((vendor, day, run), []).append(shard)
    return jobs


def _read_shards(paths):
    for path in paths:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        # worker 被 SIGKILL 時可能留半行；丟掉那一行、不丟整檔
                        print('    skip truncated line in {}'.format(path))


def _existing_rows(tree, path):
    if not os.path.exists(path):
        return []
    if tree == 'list':
        return list(_zstd_lines(path))
    import pyarrow.parquet as pq
    return pq.read_table(path).to_pylist()


def pack_run(tree, vendor_short, date_str, run, shard_paths, keep_scratch=False):
    '''一輪 shards → 分區檔。同 run 本地既有檔＝與之聯集（flow --from 重跑）。
    parsed 依 vendor_house_id 去重、後爬者勝；list／deals 是觀測／事件紀錄，全留。
    回傳 (path, n_rows)。'''
    fields, _ext = TREES[tree]
    rows = _existing_rows(tree, partition_path(tree, vendor_short, date_str, run))
    n_existing = len(rows)
    rows.extend(_read_shards(shard_paths))
    rows = [contracts.coerce_row(r, fields) for r in rows]
    if tree == 'parsed':
        latest = {}

        def stamp(row):
            return row['crawled_at'].isoformat() if row['crawled_at'] else ''
        for row in rows:
            key = row['vendor_house_id']
            if key not in latest or stamp(row) >= stamp(latest[key]):
                latest[key] = row
        rows = sorted(latest.values(), key=lambda r: r['vendor_house_id'])
    else:
        rows.sort(key=lambda r: (r['vendor_house_id'],
                                 r['seen_at'].isoformat() if r['seen_at'] else ''))

    path = partition_path(tree, vendor_short, date_str, run)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    if tree == 'list':
        proc = subprocess.Popen(['zstd', '-q', '-3', '-f', '-o', tmp],
                                stdin=subprocess.PIPE)
        for row in rows:
            row = dict(row)
            if row.get('seen_at') is not None:
                row['seen_at'] = row['seen_at'].isoformat()
            proc.stdin.write((json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8'))
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError('zstd failed writing {}'.format(tmp))
    else:
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pa.Table.from_pylist(rows, schema=contracts.arrow_schema(fields))
        pq.write_table(table, tmp, compression='zstd')
    os.replace(tmp, path)
    if n_existing:
        print('    merged with existing {} rows of {}'.format(n_existing, os.path.basename(path)))
    if not keep_scratch:
        for shard in shard_paths:
            os.unlink(shard)
        for parent in {os.path.dirname(p) for p in shard_paths}:
            try:
                os.rmdir(parent)
            except OSError:
                pass
    return path, len(rows)


def upload(bucket, tree, vendor_short, date_str, run, path):
    '''上 S3。key 帶 run，正常情況永不與既有物件相撞；同 run 重跑（本地已
    聯集）才會覆蓋同 key，且覆蓋內容是超集——印出來讓 log 看得到。'''
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client('s3')
    key = s3_key(tree, vendor_short, date_str, run)
    try:
        s3.head_object(Bucket=bucket, Key=key)
        print('    NOTE overwriting existing s3://{}/{} (same run re-packed, union)'.format(
            bucket, key))
    except ClientError as err:
        if err.response.get('Error', {}).get('Code') not in ('404', 'NoSuchKey', 'NotFound'):
            raise
    s3.upload_file(path, bucket, key)
    print('    uploaded s3://{}/{}'.format(bucket, key))
    return key


def local_partitions(tree, date_str):
    '''本地 <tree>/<vendor>/<date>/ 下的分區檔 → [(vendor, run, path)]。'''
    out = []
    base = os.path.join(artifact_dir(), tree)
    if not os.path.isdir(base):
        return out
    ext = '.' + TREES[tree][1]
    for vendor in sorted(os.listdir(base)):
        ddir = os.path.join(base, vendor, date_str)
        if not os.path.isdir(ddir):
            continue
        for name in sorted(os.listdir(ddir)):
            if name.endswith(ext):
                out.append((vendor, name[:-len(ext)], os.path.join(ddir, name)))
    return out


def reupload_missing(bucket, tree, date_str):
    '''把本地已打包、S3 上還沒有的分區檔補上（上傳失敗後的補救，例如 S3 policy
    尚未 apply）。已存在的 key 一律不動。回傳 (uploaded, skipped)。'''
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client('s3')
    uploaded = skipped = 0
    for vendor, run, path in local_partitions(tree, date_str):
        key = s3_key(tree, vendor, date_str, run)
        try:
            s3.head_object(Bucket=bucket, Key=key)
            skipped += 1
            continue
        except ClientError as err:
            if err.response.get('Error', {}).get('Code') not in ('404', 'NoSuchKey', 'NotFound'):
                raise
        s3.upload_file(path, bucket, key)
        print('    uploaded s3://{}/{}'.format(bucket, key))
        uploaded += 1
    return uploaded, skipped
