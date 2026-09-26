'''台北時區工具：Django `timezone.localtime／now／make_aware` 的無 Django 等價物。

Django 設定是 TIME_ZONE='Asia/Taipei'、USE_TZ=True，底層就是 zoneinfo；
這裡照同樣語意實作，輸出（isoformat、strftime('%Z')＝'CST'）與 Django 一致。
'''
from datetime import datetime, timezone as _utc_mod
from zoneinfo import ZoneInfo

TPE = ZoneInfo('Asia/Taipei')
UTC = _utc_mod.utc


def now():
    '''aware UTC now（Django timezone.now()，USE_TZ=True）。'''
    return datetime.now(UTC)


def localtime(value=None):
    '''aware datetime 轉台北；不給＝現在（Django timezone.localtime()）。naive 值丟 ValueError（同 Django）。'''
    if value is None:
        value = now()
    if value.tzinfo is None:
        raise ValueError('localtime() cannot be applied to a naive datetime')
    return value.astimezone(TPE)


def make_aware(value):
    '''naive datetime 視為台北時間（Django make_aware 用 default timezone）。'''
    if value.tzinfo is not None:
        raise ValueError('Not naive datetime (tzinfo is already set)')
    return value.replace(tzinfo=TPE)


def target_datetime():
    '''rental.models._get_target_date 的等價物：TWRH_TARGET_DATE（naive）或台北現在。'''
    import os
    override = os.environ.get('TWRH_TARGET_DATE')
    if override:
        return datetime.strptime(override, '%Y-%m-%d')
    return localtime()
