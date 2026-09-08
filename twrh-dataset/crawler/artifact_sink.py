'''list stub／parsed 列直寫 scratch（Phase 4a／4b 的爬取側）。

實作住在 rental.artifacts／rental.contracts（django 樹），理由同
crawler/raw_sink.py：manage.py 行程 import 不到 crawler 套件。這裡只是
scrapy 側的轉發。
'''
from rental.artifacts import ShardWriter, run_id, vendor_dirname  # noqa: F401
from rental.contracts import (  # noqa: F401
    list_fingerprint, list_stub, parsed_row)


def enabled():
    import os
    return os.environ.get('TWRH_ARTIFACT_SINK', '1') == '1'
