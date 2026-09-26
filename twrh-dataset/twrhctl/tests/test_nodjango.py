'''twrhctl 的無 DB 測試（S6）。

    poetry run python -m unittest discover -s twrhctl/tests -t .

1. 每支指令在獨立行程 import，行程裡不得出現 django 模組（這是 twrhctl 存在的理由）。
2. 三個 Django 等價物與原版逐字相同：台北時區格式、DjangoJSONEncoder、Paginator 分頁。
3. shadowcheck 的比對函數：parquet 逐列逐欄、JSON 差異路徑。
'''
import datetime as dt
import decimal
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def _commands():
    names = sorted(f[:-3] for f in os.listdir(os.path.join(BASE, 'twrhctl', 'commands'))
                   if f.endswith('.py') and not f.startswith('_'))
    assert names, 'no commands found'
    return names


class NoDjangoImportTests(unittest.TestCase):
    def test_every_command_imports_without_django(self):
        code = ('import importlib, sys\n'
                'import twrhctl\n'
                'for name in sys.argv[1:]:\n'
                '    importlib.import_module("twrhctl.commands." + name)\n'
                'leaked = [m for m in sys.modules if m == "django" or m.startswith("django.")]\n'
                'print(leaked[:5])\n'
                'sys.exit(1 if leaked else 0)\n')
        proc = subprocess.run([sys.executable, '-c', code, *_commands()], cwd=BASE,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_main_help_lists_all_commands(self):
        proc = subprocess.run([sys.executable, '-m', 'twrhctl'], cwd=BASE, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in _commands():
            self.assertIn(name, proc.stdout)

    def test_db_only_modes_are_refused(self):
        env = dict(os.environ, TWRH_HOUSE_DB='1')
        proc = subprocess.run([sys.executable, '-m', 'twrhctl', 'manifest', '--date', '2026-09-26',
                               '--no-upload'], cwd=BASE, capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('需要 DB', proc.stderr)


_EQUIV_SCRIPT = r"""
import datetime as dt, decimal, json, sys, uuid
# 真的 Django 要先載入：twrh-dataset/django/ 自己也是個 package（有 __init__.py），
# 在 twrh-dataset 目錄下 import django 會拿到它。所以 twrh-dataset 只能加在 sys.path 末尾
from django.core.serializers.json import DjangoJSONEncoder as RealEncoder
from django.core.paginator import Paginator as RealPaginator
sys.path.append(sys.argv[1])
from twrhctl.export.json_writer import DjangoJSONEncoder as OurEncoder
from twrhctl.export.raw_export import Paginator as OurPaginator
from twrhctl import tz

tpe = dt.timezone(dt.timedelta(hours=8))
values = [
    dt.datetime(2026, 9, 26, 3, 18, 7, 123456, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 9, 26, 3, 18, 7, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 9, 26, 11, 18, 7, 5, tzinfo=tpe),
    dt.datetime(2026, 9, 26, 11, 18),
    dt.date(2026, 9, 26), dt.time(3, 4, 5, 678901),
    decimal.Decimal('12.50'), uuid.UUID('12345678-1234-5678-1234-567812345678'),
]
for v in values:
    a, b = json.dumps(v, cls=OurEncoder), json.dumps(v, cls=RealEncoder)
    assert a == b, (v, a, b)

for n in (0, 1, 2999, 3000, 3001, 7000):
    data = list(range(n))
    real, ours = RealPaginator(data, 3000), OurPaginator(data, 3000)
    assert real.count == ours.count, n
    assert list(real.page_range) == list(ours.page_range), n
    for p in real.page_range:
        assert list(real.page(p)) == list(ours.page(p)), (n, p)

value = dt.datetime(2026, 9, 25, 16, 0, tzinfo=dt.timezone.utc)
assert tz.localtime(value).strftime('%Y-%m-%d %H:%M:%S %Z') == '2026-09-26 00:00:00 CST'
assert tz.make_aware(dt.datetime(2026, 9, 26)).isoformat() == '2026-09-26T00:00:00+08:00'
try:
    tz.localtime(dt.datetime(2026, 9, 26))
except ValueError:
    pass
else:
    raise AssertionError('naive localtime should raise')
print('equivalent')
"""


class EquivalenceTests(unittest.TestCase):
    '''等價物對 Django 原版逐字相同：DjangoJSONEncoder、Paginator、台北時區格式。
    子行程在別的目錄跑（避開 twrh-dataset/django 遮蔽真正的 Django）。'''

    def test_equivalents_match_django(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, '-c', _EQUIV_SCRIPT, BASE], cwd=tmp,
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('equivalent', proc.stdout)


class ShadowHelperTests(unittest.TestCase):
    def _write(self, path, rows):
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(rows), path)

    def test_parquet_diff(self):
        from twrhctl.commands.shadowcheck import _parquet_diff
        with tempfile.TemporaryDirectory() as tmp:
            a, b, c = (os.path.join(tmp, n) for n in ('a.parquet', 'b.parquet', 'c.parquet'))
            rows = [{'vendor_house_id': '2', 'x': 1}, {'vendor_house_id': '1', 'x': 2}]
            self._write(a, rows)
            self._write(b, list(reversed(rows)))          # 列序不同＝相同
            self._write(c, [{'vendor_house_id': '2', 'x': 1}, {'vendor_house_id': '1', 'x': 3}])
            self.assertIsNone(_parquet_diff(a, b))
            self.assertEqual(_parquet_diff(a, c), {'columns': {'x': 1}})
            self.assertIn('missing', _parquet_diff(a, os.path.join(tmp, 'nope.parquet')))

    def test_json_diff_ignores_generated_at(self):
        from twrhctl.commands.shadowcheck import _json_diff, _strip_generated
        a = {'generated_at': 'x', 'counts': {'n': 1, 'm': 2}}
        b = {'generated_at': 'y', 'counts': {'n': 1, 'm': 3}}
        self.assertEqual(_json_diff(_strip_generated(a), _strip_generated(a)), [])
        self.assertEqual(_json_diff(_strip_generated(a), _strip_generated(b)), ['counts.m: 2 != 3'])


if __name__ == '__main__':
    unittest.main()
