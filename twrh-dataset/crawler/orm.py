'''Django ORM 的延遲入口（S6）。

S5 之後 DB 已退場，爬蟲行程預設不 django.setup()（general_settings 只在 rental.vendors.needs_orm()
為真——house DB 回退或 queue 回到 DB 記帳——時才 setup）。pipeline／persist_queue／spider 裡
DB 分支用到的 model、connection、transaction、F／Q 改從這裡拿：模組層只是代理，第一次真的被
用到時才 import Django。

檔案時代若有程式路徑意外碰到 ORM：代理照樣把 Django 起起來（行為與改之前相同——之前是一律
setup、之後查詢因沒有 DB 而失敗），同時打一條 WARNING 標出是誰，平行比對／本機驗收看得到。
'''
import importlib
import logging
import os
import sys

_state = {'ready': False}


def ready():
    return _state['ready']


def setup():
    if _state['ready']:
        return
    django_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'django')
    if django_dir not in sys.path:
        sys.path.append(django_dir)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
    # Allow synchronous Django ORM calls in Scrapy's Twisted async context
    os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
    import django
    django.setup()
    _state['ready'] = True


def _apps_ready():
    if 'django.apps' not in sys.modules:
        return False
    from django.apps import apps
    return apps.ready


class _Lazy:
    __slots__ = ('_module', '_name', '_obj')

    def __init__(self, module, name):
        self._module = module
        self._name = name
        self._obj = None

    def _target(self):
        if self._obj is None:
            if not _state['ready'] and _apps_ready():
                _state['ready'] = True   # 已在 Django 行程裡（manage.py test／指令 import 了爬蟲模組）
            if not _state['ready']:
                logging.warning('ORM touched outside DB mode: %s.%s — setting up Django lazily',
                                self._module, self._name)
                setup()
            self._obj = getattr(importlib.import_module(self._module), self._name)
        return self._obj

    def __getattr__(self, attr):
        return getattr(self._target(), attr)

    def __call__(self, *args, **kwargs):
        return self._target()(*args, **kwargs)

    def __repr__(self):
        return '<lazy {}.{}>'.format(self._module, self._name)


House = _Lazy('rental.models', 'House')
HouseTS = _Lazy('rental.models', 'HouseTS')
HouseEtc = _Lazy('rental.models', 'HouseEtc')
Author = _Lazy('rental.models', 'Author')
RequestTS = _Lazy('crawlerrequest.models', 'RequestTS')
Point = _Lazy('django.contrib.gis.geos', 'Point')
connection = _Lazy('django.db', 'connection')
transaction = _Lazy('django.db', 'transaction')
F = _Lazy('django.db.models', 'F')
Q = _Lazy('django.db.models', 'Q')
