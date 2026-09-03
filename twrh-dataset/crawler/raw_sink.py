'''raw 直寫 scratch（architecture-roadmap 3-1，案 B 的爬取側）。

實作住在 rental.raws（django 樹）——manage.py 行程（rawpack）import
不到 crawler 套件（image 是 poetry install --no-root，2026-09-04 首跑
實踩），這裡只留 scrapy 側的既有 import 路徑轉發。設計說明見
rental/raws.py。
'''
from rental.raws import (  # noqa: F401
    enabled, scratch_dir, raw_dir, vendor_dirname, day_dir, write_raw)
