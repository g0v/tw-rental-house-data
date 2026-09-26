
import os
from datetime import datetime
from rental import tz as timezone   # S6：無 Django 的台北時區工具（同介面）

def now_tuple():
    override = os.environ.get('TWRH_TARGET_DATE')
    if override:
        d = datetime.strptime(override, '%Y-%m-%d')
        return [d.year, d.month, d.day, 0]
    now = timezone.localtime(timezone.now())
    # Let's do it once for now
    return [now.year, now.month, now.day, 0]
    # return [now.year, now.month, now.day, now.hour - now.hour % 12]
