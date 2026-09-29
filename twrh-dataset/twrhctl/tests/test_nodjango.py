'''twrhctl 的無 DB 測試（S6）。

    poetry run python -m unittest discover -s twrhctl/tests -t .

每支指令在獨立行程 import，行程裡不得出現 django 模組；Sentry 初始化也不得帶進 django。
（平行期的 Django 等價比對與 shadowcheck 測試隨 Django 退場移除——等價性由 9/27 起每晚的兩路
比對與 10/1 月包比對承擔，結果見 docs/architecture-roadmap.md。）
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

    def test_sentry_init_does_not_import_django(self):
        # 雲上有 SENTRY_DSN：sentry 的自動整合會試 import django（2026-09-26 雲上實測 exit 3）
        env = dict(os.environ, SENTRY_DSN='https://public@o0.ingest.sentry.io/0')
        code = ('import sys\nimport twrhctl\n'
                'leaked = [m for m in sys.modules if m == "django" or m.startswith("django.")]\n'
                'print(leaked)\nsys.exit(1 if leaked else 0)\n')
        proc = subprocess.run([sys.executable, '-c', code], cwd=BASE, capture_output=True,
                              text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_main_help_lists_all_commands(self):
        proc = subprocess.run([sys.executable, '-m', 'twrhctl'], cwd=BASE, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in _commands():
            self.assertIn(name, proc.stdout)


if __name__ == '__main__':
    unittest.main()
