'''shadowcheck：Django 退休前的平行比對（S6，flow 的 `nodjango` advisory stage）。

    python -m twrhctl shadowcheck [--date D] [--only a,b] [--keep]

對同一天，用 Django 路徑（`django/manage.py`，現行生產入口）與 twrhctl（無 Django）各跑一次
flow／出貨會用到的指令，逐項比對產物；最後一行印
`nodjango: AGREE｜DIFF — {...}`，flow 的 advisory_check 把它記進 checks.json。

比對項（每項獨立，一項壞不影響別項）：
  snapshot-final   twrhctl snapshotfold --only final 摺出 D−1，對 flow 剛摺好的 D−1（逐列逐欄）
  latest           twrhctl latestfold 摺出 latest(D−1)，對 flow 的總表
  snapshot-prov    twrhctl snapshotfold --only provisional 摺出 D，對 flow 的 D
                   （以上三項在影子目錄跑：輸入缺本地就從 S3 拉，輸出寫影子目錄、不上傳）
  manifest         twrhctl manifest --no-upload 寫影子 manifest 目錄，四份逐鍵對 flow 的（略 generated_at）
  qualitycheck     兩條路徑各跑 --no-slack，輸出行與 exit code 相同
  export           月初..D 的區間 export（--source snapshot）兩條路徑 CSV／統計 JSON 逐 byte；
                   每月 1 日另比 `export -p` 的月包（zip 內每個檔逐 byte）
  monthreport      當月報告兩條路徑逐鍵（略 generated_at）＋exit code
  queuefinalize    兩條路徑 --no-cleanup，輸出行＋exit code
  queuebusy        兩條路徑 --source file，輸出行＋exit code
  rawpack          兩條路徑 --reconcile-only --keep-local（各自的影子 TWRH_RAW_DIR，不碰 EFS 上的日包位置）

安全：所有子行程都清掉 SLACK_WEBHOOK_URL／SENTRY_DSN（同一件事不通知兩次）；影子產物不上傳；
flow 的正式產物只讀不寫。
'''
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta

from twrhctl import BASE
from twrhctl.base import BaseCommand, CommandError

VENDOR_NAME = '591 租屋網'
VENDOR_SHORT = '591'

ITEMS = ('snapshot-final', 'latest', 'snapshot-prov', 'manifest', 'qualitycheck',
         'export', 'monthreport', 'queuefinalize', 'queuebusy', 'rawpack')


def _base_env(extra=None):
    env = dict(os.environ)
    env['SLACK_WEBHOOK_URL'] = ''
    env['SENTRY_DSN'] = ''
    env.update(extra or {})
    return env


def _run(argv, env=None, timeout=3600):
    started = time.time()
    proc = subprocess.run(argv, cwd=BASE, env=_base_env(env), capture_output=True,
                          text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr, round(time.time() - started, 1)


def django(*args, env=None):
    return _run([sys.executable, 'django/manage.py', *args], env)


def ctl(*args, env=None):
    return _run([sys.executable, '-m', 'twrhctl', *args], env)


def _lines(text, drop=()):
    return [line for line in text.splitlines()
            if line.strip() and not any(d in line for d in drop)]


def _strip_generated(obj):
    if isinstance(obj, dict):
        return {k: _strip_generated(v) for k, v in obj.items() if k != 'generated_at'}
    if isinstance(obj, list):
        return [_strip_generated(v) for v in obj]
    return obj


def _json_diff(a, b, prefix=''):
    '''兩份 JSON 的差異路徑（最多 20 條）。'''
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in a or key not in b:
                out.append('{}{}: only in {}'.format(prefix, key, 'django' if key in a else 'twrhctl'))
            else:
                out.extend(_json_diff(a[key], b[key], '{}{}.'.format(prefix, key)))
    elif a != b:
        out.append('{}: {!r} != {!r}'.format(prefix.rstrip('.'), a, b)[:200])
    return out[:20]


def _parquet_diff(path_a, path_b):
    '''兩份 parquet 逐列逐欄比（以 vendor_house_id 排序）。回傳 None＝相同，否則差異摘要。'''
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    if not os.path.exists(path_a) or not os.path.exists(path_b):
        return {'missing': [p for p in (path_a, path_b) if not os.path.exists(p)]}
    a = pq.read_table(path_a)
    b = pq.read_table(path_b)
    if a.schema != b.schema:
        return {'schema': {'only_flow': sorted(set(a.schema.names) - set(b.schema.names)),
                           'only_twrhctl': sorted(set(b.schema.names) - set(a.schema.names)),
                           'types': [n for n in a.schema.names if n in b.schema.names
                                     and a.schema.field(n).type != b.schema.field(n).type]}}
    if a.num_rows != b.num_rows:
        return {'rows': [a.num_rows, b.num_rows]}
    key = 'vendor_house_id'
    a = a.take(pc.sort_indices(a, sort_keys=[(key, 'ascending')]))
    b = b.take(pc.sort_indices(b, sort_keys=[(key, 'ascending')]))
    if a.equals(b):
        return None
    cols = {}
    for name in a.schema.names:
        ca, cb = a.column(name), b.column(name)
        if not ca.equals(cb):
            la, lb = ca.to_pylist(), cb.to_pylist()
            n = sum(1 for x, y in zip(la, lb) if x != y)
            if n:
                cols[name] = n
    return {'columns': cols} if cols else None


class Command(BaseCommand):
    help = 'Run flow/publish commands through Django and twrhctl, compare outputs (S6 parallel run)'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--only', help='逗號分隔的比對項（預設全部）：' + ','.join(ITEMS))
        parser.add_argument('--work-dir', help='影子目錄（預設暫存、跑完刪）')
        parser.add_argument('--keep', action='store_true', help='跑完保留影子目錄')

    def handle(self, *_args, **options):
        raw = options['date'] or os.environ.get('TWRH_TARGET_DATE')
        try:
            self.day = datetime.strptime(raw, '%Y-%m-%d').date() if raw else date.today()
        except ValueError:
            raise CommandError('--date 需為 YYYY-MM-DD')
        items = ITEMS if not options['only'] else tuple(options['only'].split(','))
        unknown = [i for i in items if i not in ITEMS]
        if unknown:
            raise CommandError('unknown items: {}'.format(unknown))

        self.work = options['work_dir'] or tempfile.mkdtemp(
            prefix='nodjango-', dir=os.environ.get('TWRHCTL_SHADOW_TMP'))
        os.makedirs(self.work, exist_ok=True)
        from rental import artifacts
        self.real_artifacts = artifacts.artifact_dir()
        self.shadow_artifacts = os.path.join(self.work, 'artifacts')
        # 正式 artifact 目錄顯式釘住：rawpack 的影子 TWRH_RAW_DIR 不能把預設的 artifact_dir（跟 raws 同層）
        # 一起帶走，否則檔案 queue 讀空目錄、兩邊都是 0 而「相同」
        self.env_date = {'TWRH_TARGET_DATE': self.day.isoformat(),
                         'TWRH_ARTIFACT_DIR': self.real_artifacts}

        results = {}
        for item in items:
            try:
                verdict, detail = getattr(self, 'check_' + item.replace('-', '_'))()
            except Exception as err:  # noqa: BLE001 — 一項壞不擋別項
                verdict, detail = 'error', '{}: {}'.format(type(err).__name__, err)[:300]
            results[item] = verdict
            print('  [{}] {}{}'.format(item, verdict,
                                       '' if detail is None else ' — ' + json.dumps(
                                           detail, ensure_ascii=False, default=str)[:600]),
                  flush=True)

        if not options['keep'] and not options['work_dir']:
            shutil.rmtree(self.work, ignore_errors=True)
        agree = all(v in ('AGREE', 'n/a') for v in results.values())
        summary = {'date': self.day.isoformat(), 'items': results}
        print('nodjango: {} — {}'.format('AGREE' if agree else 'DIFF',
                                         json.dumps(summary, ensure_ascii=False)), flush=True)

    # ---- 共用 ------------------------------------------------------------

    def _compare_cmd(self, dj_args, ctl_args, env=None, drop=()):
        rc_dj, out_dj, err_dj, t_dj = django(*dj_args, env=env)
        rc_ctl, out_ctl, err_ctl, t_ctl = ctl(*ctl_args, env=env)
        lines_dj, lines_ctl = _lines(out_dj, drop), _lines(out_ctl, drop)
        detail = {'rc': [rc_dj, rc_ctl], 'sec': [t_dj, t_ctl]}
        if rc_dj == rc_ctl and lines_dj == lines_ctl:
            return 'AGREE', detail
        diff = [(x, y) for x, y in zip(lines_dj, lines_ctl) if x != y][:3]
        detail.update({'n_lines': [len(lines_dj), len(lines_ctl)], 'first_diffs': diff,
                       'stderr_tail': [err_dj.strip().splitlines()[-1:], err_ctl.strip().splitlines()[-1:]]})
        return 'DIFF', detail

    def _shadow_env(self):
        return {**self.env_date, 'TWRH_ARTIFACT_DIR': self.shadow_artifacts}

    def _snapshot(self, base, day):
        return os.path.join(base, 'snapshot', VENDOR_SHORT, day.isoformat() + '.parquet')

    # ---- fold 三項：影子目錄重摺，對 flow 產物 -------------------------------

    def _fold(self, args, real_path, shadow_path):
        rc, out, err, sec = ctl(*args, env=self._shadow_env())
        if rc:
            return 'DIFF', {'twrhctl_rc': rc, 'stderr_tail': err.strip().splitlines()[-3:]}
        diff = _parquet_diff(real_path, shadow_path)
        return ('AGREE', {'sec': sec}) if diff is None else ('DIFF', diff)

    def check_snapshot_final(self):
        yesterday = self.day - timedelta(days=1)
        return self._fold(
            ['snapshotfold', '--date', self.day.isoformat(), '--only', 'final', '--no-upload'],
            self._snapshot(self.real_artifacts, yesterday),
            self._snapshot(self.shadow_artifacts, yesterday))

    def check_latest(self):
        yesterday = (self.day - timedelta(days=1)).isoformat()
        rel = os.path.join('latest', VENDOR_SHORT, 'daily', yesterday + '.parquet')
        return self._fold(['latestfold', '--date', self.day.isoformat(), '--no-upload'],
                          os.path.join(self.real_artifacts, rel),
                          os.path.join(self.shadow_artifacts, rel))

    def check_snapshot_prov(self):
        return self._fold(
            ['snapshotfold', '--date', self.day.isoformat(), '--only', 'provisional', '--no-upload'],
            self._snapshot(self.real_artifacts, self.day),
            self._snapshot(self.shadow_artifacts, self.day))

    # ---- manifest：讀正式分區、寫影子 manifest 目錄 --------------------------

    def check_manifest(self):
        from crawlerrequest import manifest_files
        shadow_dir = os.path.join(self.work, 'manifests')
        rc, out, err, sec = ctl('manifest', '--date', self.day.isoformat(), '--no-upload',
                                env={**self.env_date, 'TWRH_MANIFEST_DIR': shadow_dir})
        if rc:
            return 'DIFF', {'twrhctl_rc': rc, 'stderr_tail': err.strip().splitlines()[-3:]}
        diffs = {}
        for stage in ('list', 'detail', 'deals', 'snapshot'):
            real = manifest_files.load_manifest(self.day.isoformat(), stage)
            shadow = manifest_files.load_manifest(self.day.isoformat(), stage, shadow_dir)
            if real is None or shadow is None:
                diffs[stage] = 'missing ({})'.format('flow' if real is None else 'twrhctl')
                continue
            d = _json_diff(_strip_generated(real), _strip_generated(shadow))
            if d:
                diffs[stage] = d
        return ('AGREE', {'sec': sec}) if not diffs else ('DIFF', diffs)

    # ---- 兩條路徑各跑一次 ------------------------------------------------------

    def check_qualitycheck(self):
        args = ['qualitycheck', '--date', self.day.isoformat(), '--no-slack']
        return self._compare_cmd(args, args, env=self.env_date)

    def check_queuefinalize(self):
        return self._compare_cmd(['queuefinalize', '--no-cleanup'],
                                 ['queuefinalize', '--no-cleanup', '--no-slack'],
                                 env=self.env_date)

    def check_queuebusy(self):
        args = ['queuebusy', '--vendor', VENDOR_NAME, '--source', 'file',
                '--date', self.day.isoformat()]
        return self._compare_cmd(args, args, env=self.env_date)

    def check_rawpack(self):
        args = ['rawpack', '--reconcile-only', '--keep-local', '--date', self.day.isoformat()]
        rc_dj, out_dj, err_dj, t_dj = django(*args, env={
            **self.env_date, 'TWRH_RAW_DIR': os.path.join(self.work, 'raw-django')})
        rc_ctl, out_ctl, err_ctl, t_ctl = ctl(*args, env={
            **self.env_date, 'TWRH_RAW_DIR': os.path.join(self.work, 'raw-twrhctl')})
        drop = ('merged base:',)
        a, b = _lines(out_dj, drop), _lines(out_ctl, drop)
        detail = {'rc': [rc_dj, rc_ctl], 'sec': [t_dj, t_ctl]}
        if rc_dj == rc_ctl and a == b:
            return 'AGREE', detail
        detail['first_diffs'] = [(x, y) for x, y in zip(a, b) if x != y][:3] or [a[-1:], b[-1:]]
        return 'DIFF', detail

    def check_monthreport(self):
        month = self.day.strftime('%Y%m')
        dj_dir, ctl_dir = os.path.join(self.work, 'mr-django'), os.path.join(self.work, 'mr-twrhctl')
        rc_dj, _o1, err_dj, t_dj = django('monthreport', '--month', month, '-o', dj_dir, env=self.env_date)
        rc_ctl, _o2, err_ctl, t_ctl = ctl('monthreport', '--month', month, '-o', ctl_dir, env=self.env_date)
        name = '{}.report.json'.format(month)
        detail = {'rc': [rc_dj, rc_ctl], 'sec': [t_dj, t_ctl]}
        try:
            with open(os.path.join(dj_dir, name)) as f:
                a = _strip_generated(json.load(f))
            with open(os.path.join(ctl_dir, name)) as f:
                b = _strip_generated(json.load(f))
        except OSError as err:
            detail['missing'] = str(err)
            return 'DIFF', detail
        d = _json_diff(a, b)
        if rc_dj == rc_ctl and not d:
            return 'AGREE', detail
        detail['diffs'] = d
        return 'DIFF', detail

    def check_export(self):
        start = self.day.replace(day=1)
        window = ['-f', start.strftime('%Y%m%d'), '-t', self.day.strftime('%Y%m%d'),
                  '--source', 'snapshot']
        out_dj, out_ctl = os.path.join(self.work, 'export-django'), os.path.join(self.work, 'export-twrhctl')
        rc_dj, _o1, err_dj, t_dj = django('export', *window, '-o', out_dj, env=self.env_date)
        rc_ctl, _o2, err_ctl, t_ctl = ctl('export', *window, '-o', out_ctl, env=self.env_date)
        detail = {'window': [start.isoformat(), self.day.isoformat()], 'rc': [rc_dj, rc_ctl],
                  'sec': [t_dj, t_ctl]}
        same = rc_dj == rc_ctl == 0
        for ext in ('.csv', '.json'):
            a, b = out_dj + ext, out_ctl + ext
            ok = os.path.exists(a) and os.path.exists(b) and filecmp.cmp(a, b, shallow=False)
            detail[ext.lstrip('.')] = 'same' if ok else 'differ'
            same = same and ok
        if self.day.day == 1:
            zip_verdict = self._compare_month_zip()
            detail['month_zip'] = zip_verdict
            same = same and zip_verdict == 'same'
        return ('AGREE' if same else 'DIFF'), detail

    def _compare_month_zip(self):
        '''1 日：flow 的 export stage 已用 Django 產出上月月包；twrhctl 在影子目錄再產一份，
        zip 內每個檔逐 byte 比（zip 本身的時間戳不同，不比容器）。'''
        prev = self.day - timedelta(days=1)
        zip_dir = os.path.join(self.work, 'zip')
        os.makedirs(zip_dir, exist_ok=True)
        rc, _o, err, _t = ctl('export', '-p', env={**self.env_date, 'TWRHCTL_EXPORT_ZIP_DIR': zip_dir})
        if rc:
            return 'twrhctl rc {}: {}'.format(rc, err.strip().splitlines()[-1:])
        real_dir = os.path.join(BASE, 'datas')
        out = []
        for kind in ('CSV', 'JSON'):
            name = '[{}][{}][Raw] TW-Rental-Data.zip'.format(prev.strftime('%Y%m'), kind)
            a, b = os.path.join(real_dir, name), os.path.join(zip_dir, name)
            if not (os.path.exists(a) and os.path.exists(b)):
                out.append('{} missing'.format(kind))
                continue
            with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
                if sorted(za.namelist()) != sorted(zb.namelist()):
                    out.append('{} members differ'.format(kind))
                    continue
                for member in za.namelist():
                    if za.read(member) != zb.read(member):
                        out.append('{} {} differs'.format(kind, member))
        return 'same' if not out else '; '.join(out)[:300]
