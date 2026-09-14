'''檔案化靜態分片 queue（Phase 4e；architecture-roadmap〈已拍板 2026-09-04〉）。

queue 真正的需求只有三條：N 個 worker 不重複、每筆有顯式終結狀態、收工能算
seeds == terminals。這裡用檔案滿足，不需要 DB server：

    <artifact_dir>/queue/<vendor>/<date>/<type>/seeds/<run>.jsonl            種子（單寫者：生種子的行程）
    <artifact_dir>/queue/<vendor>/<date>/<type>/terminals/<run>/<worker>.jsonl 終結紀錄（每 worker 一檔、append-only）

- **記帳按 key**：一行 seed＝一個工作項（key 唯一）；終結行 {key, status,
  attempts, error, http, at}。同 key 多行＝重試史，摺疊時 done 勝、其次 dead、
  其次 attempts 最大的 failed。沒有 in_flight——「未終結」即「還要做」。
- **分片**：worker i／N 對「剩餘集合」排序後依位置輪流分（不用 hash 取模），
  所有 worker 無通訊算出同一結果；attempts 跨檔累計（取該 key 最大值）。
- **雙軌期（4e 第一步）**：DB queue 仍是認領來源，這裡只是同步記帳；key＝
  RequestTS.id，`filequeuecheck` 對 DB 逐型比對。
- **S4a（4e 第二步，TWRH_QUEUE_SOURCE=file）**：認領改由這裡出——`claimable()` 對
  「當日全部 seeds」（不是剩餘集合）位置輪分再濾掉已終結；分片對象是靜態集合，所以
  worker 各自在任意時刻重啟（batch 迴圈）算出的分片都一致、永不重疊（對剩餘集合輪分
  只在所有 worker 同時開新一輪時成立，交錯重啟會整片撞車）。死掉的 worker 留下的
  分片由收尾的單 worker 補掃（count=1 拿全部剩餘）。DB 在 S4a 仍照寫一天
  （TWRH_QUEUE_DB=1，key 仍＝RequestTS.id）供 filequeuecheck 對帳；S4b 停寫後
  key 改 make_key(seed) 自派。
- **S4b（TWRH_QUEUE_SOURCE=file＋TWRH_QUEUE_DB=0，flow 預設）**：request_ts 不再有人寫；
  `db_bookkeeping()` 是唯一判準——queuefinalize／seedcheck／rawpack 對帳、detail 的
  seed_mode=new 去重都改讀這裡的 seeds／terminals，filequeuecheck 沒有對照物即 skip。
  drop request_ts 另一步（一晚無紅後）。回退＝環境 TWRH_QUEUE_DB=1（記帳鏡像回來）或
  TWRH_QUEUE_SOURCE=db。
- **心跳**：沒有 in_flight，「有人在爬」改看 active/<run>/<worker>.json 的 mtime
  （queuebusy）；SIGKILL 殘留的心跳過窗即失效。

不 import Django（manage.py／scrapy／離線工具三處共用，4f 去 Django 時
它就是 queue 的全部）。
'''
import glob
import json
import os
from datetime import datetime, timezone

from rental.artifacts import artifact_dir, run_id  # noqa: F401

STATUS_ORDER = {'done': 3, 'dead': 2, 'failed': 1}


def db_bookkeeping():
    '''request_ts 還有沒有人寫（S4a 雙軌＝True；S4b＝False）。DB 認領（TWRH_QUEUE_SOURCE=db）
    恆 True；檔案認領時看 TWRH_QUEUE_DB（預設 1，flow 自 S4b 起預設 0）。'''
    if os.environ.get('TWRH_QUEUE_SOURCE', 'db') != 'file':
        return True
    return os.environ.get('TWRH_QUEUE_DB', '1') == '1'


def seed_ids(vendor_short, date_str, type_name):
    '''當日該型所有 seed 的 id（含已終結）；detail seed_mode=new 用它不重排同日已有列的物件。'''
    seeds, _dup = load_seeds(vendor_short, date_str, type_name)
    return {seed.get('id') for seed in seeds.values() if isinstance(seed, dict)}


def queue_dir(vendor_short, date_str, type_name):
    return os.path.join(artifact_dir(), 'queue', vendor_short, date_str, type_name)


def seeds_path(vendor_short, date_str, type_name, run):
    return os.path.join(queue_dir(vendor_short, date_str, type_name), 'seeds', run + '.jsonl')


def terminals_dir(vendor_short, date_str, type_name, run):
    return os.path.join(queue_dir(vendor_short, date_str, type_name), 'terminals', run)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class _Appender:
    def __init__(self, path):
        self.path = path
        self._f = None

    def write(self, row):
        if self._f is None:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._f = open(self.path, 'a', encoding='utf-8')
        self._f.write(json.dumps(row, ensure_ascii=False) + '\n')
        self._f.flush()

    def close(self):
        if self._f is not None:
            self._f.close()
            self._f = None


class SeedsWriter(_Appender):
    def __init__(self, vendor_short, date_str, type_name, run):
        super().__init__(seeds_path(vendor_short, date_str, type_name, run))

    def append(self, key, seed):
        self.write({'key': str(key), 'seed': seed, 'at': _now()})


class TerminalWriter(_Appender):
    def __init__(self, vendor_short, date_str, type_name, run, worker):
        super().__init__(os.path.join(
            terminals_dir(vendor_short, date_str, type_name, run), worker + '.jsonl'))

    def append(self, key, status, attempts, error=None, http=None):
        assert status in STATUS_ORDER, status
        self.write({'key': str(key), 'status': status, 'attempts': int(attempts),
                    'error': error, 'http': http, 'at': _now()})


def _lines(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue   # 被 SIGKILL 的半行


def load_seeds(vendor_short, date_str, type_name):
    '''當日該型全部 run 的種子：{key: seed}；重複 key 只算一次（另回傳重複數）。'''
    seeds, dup = {}, 0
    for path in sorted(glob.glob(os.path.join(
            queue_dir(vendor_short, date_str, type_name), 'seeds', '*.jsonl'))):
        for row in _lines(path):
            if row['key'] in seeds:
                dup += 1
            seeds[row['key']] = row['seed']
    return seeds, dup


def load_terminals(vendor_short, date_str, type_name, max_attempts=3):
    '''當日該型全部 run／worker 的終結紀錄摺疊成 {key: {status, attempts, error}}。
    done 勝於 dead 勝於 failed；attempts 取最大；failed 且 attempts>=max 視為 dead。'''
    folded = {}
    for path in sorted(glob.glob(os.path.join(
            queue_dir(vendor_short, date_str, type_name), 'terminals', '*', '*.jsonl'))):
        for row in _lines(path):
            cur = folded.get(row['key'])
            attempts = max(row.get('attempts', 0), cur['attempts'] if cur else 0)
            status = row['status']
            if cur and STATUS_ORDER[cur['status']] > STATUS_ORDER[status]:
                status = cur['status']
            error = row.get('error') if status != 'done' else None
            if cur and status == cur['status'] and cur.get('error') and not error:
                error = cur['error']
            folded[row['key']] = {'status': status, 'attempts': attempts, 'error': error}
    for entry in folded.values():
        if entry['status'] == 'failed' and entry['attempts'] >= max_attempts:
            entry['status'] = 'dead'
    return folded


def reconcile(vendor_short, date_str, type_name, max_attempts=3):
    '''seeds == terminals 的檔案版：回傳計數與 error 分類。
    residue＝有種子但未終結（含仍可重試的 failed）；orphans＝有終結行卻沒種子。'''
    seeds, dup = load_seeds(vendor_short, date_str, type_name)
    terminals = load_terminals(vendor_short, date_str, type_name, max_attempts)
    done = dead = retriable = 0
    errors = {}
    for key in seeds:
        t = terminals.get(key)
        if t is None:
            continue
        if t['status'] == 'done':
            done += 1
        elif t['status'] == 'dead':
            dead += 1
            errors[t['error'] or 'unknown'] = errors.get(t['error'] or 'unknown', 0) + 1
        else:
            retriable += 1
            errors[t['error'] or 'unknown'] = errors.get(t['error'] or 'unknown', 0) + 1
    orphans = len(set(terminals) - set(seeds))
    return {
        'seeds': len(seeds), 'done': done, 'dead': dead,
        'residue': len(seeds) - done - dead, 'retriable_failed': retriable,
        'duplicate_seed_lines': dup, 'orphan_terminals': orphans, 'errors': errors,
    }


def remaining(vendor_short, date_str, type_name, max_attempts=3):
    '''還要做的工作項：{key: (seed, attempts)}（未終結，含可重試的 failed）。'''
    seeds, _dup = load_seeds(vendor_short, date_str, type_name)
    terminals = load_terminals(vendor_short, date_str, type_name, max_attempts)
    out = {}
    for key, seed in seeds.items():
        t = terminals.get(key)
        if t is None:
            out[key] = (seed, 0)
        elif t['status'] == 'failed':
            out[key] = (seed, t['attempts'])
    return out


def shard(keys, index, count):
    '''位置輪分：排序後第 index、index+count、… 個。所有 worker 各自算、結果一致；
    剩餘集合小時也精確均等（hash 取模做不到）。'''
    if not 0 <= index < count:
        raise ValueError('index {} out of range for count {}'.format(index, count))
    ordered = sorted(keys)
    return ordered[index::count]


def make_key(seed):
    '''檔案自派 key（S4b，DB 不再給 id）：seed 各欄依名稱排序串起，同 seed 同 key，
    重排同一戶自然去重、attempts 跨輪累計。'''
    if isinstance(seed, dict):
        return '|'.join('{}={}'.format(k, seed[k]) for k in sorted(seed))
    return str(seed)


def claimable(vendor_short, date_str, type_name, index=0, count=1, max_attempts=3):
    '''worker index／count 的認領清單：[(key, seed, attempts)]。分片對「當日全部 seeds」
    位置輪分（靜態、重啟一致），再去掉已終結；新種子（attempts 0）排前、可重試的 failed
    排後（同 DB 版 order by attempts）。'''
    seeds, _dup = load_seeds(vendor_short, date_str, type_name)
    terminals = load_terminals(vendor_short, date_str, type_name, max_attempts)
    out = []
    for key in shard(list(seeds), index, count):
        t = terminals.get(key)
        if t is None:
            out.append((key, seeds[key], 0))
        elif t['status'] == 'failed':
            out.append((key, seeds[key], t['attempts']))
    out.sort(key=lambda x: (x[2], _natural(x[0])))
    return out


def _natural(key):
    return (0, int(key)) if key.isdigit() else (1, key)


def has_seed_matching(vendor_short, date_str, type_name, **filters):
    '''當日該型是否有 seed 符合條件（PersistQueue.has_seed 的檔案版；filters 對 seed 的欄位）。'''
    seeds, _dup = load_seeds(vendor_short, date_str, type_name)
    for seed in seeds.values():
        if isinstance(seed, dict) and all(seed.get(k) == v for k, v in filters.items()):
            return True
    return False


def active_dir(vendor_short, date_str, type_name, run):
    return os.path.join(queue_dir(vendor_short, date_str, type_name), 'active', run)


class Heartbeat:
    '''worker 存活標記：active/<run>/<worker>.json，touch 更新 mtime、收工刪除。'''

    def __init__(self, vendor_short, date_str, type_name, run, worker):
        self.path = os.path.join(active_dir(vendor_short, date_str, type_name, run), worker + '.json')

    def touch(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'at': _now()}, f)

    def clear(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def active_workers(vendor_short, date_str, hours=2.0):
    '''近 hours 小時內 touch 過心跳的 worker 檔（跨所有 type／run）；queuebusy 用。'''
    import time
    cutoff = time.time() - hours * 3600
    base = os.path.join(artifact_dir(), 'queue', vendor_short, date_str)
    return sorted(p for p in glob.glob(os.path.join(base, '*', 'active', '*', '*.json'))
                  if os.path.getmtime(p) >= cutoff)


def type_names(vendor_short, date_str):
    base = os.path.join(artifact_dir(), 'queue', vendor_short, date_str)
    if not os.path.isdir(base):
        return []
    return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
