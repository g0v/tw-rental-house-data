'''自訂 scrapy 訊號 —— 定義已上移至 scrapy_twrh.signals（dx 2-1，2026-08-25）。

這裡只 re-export，讓 crawler 內既有的 import 路徑（persist_queue、pipelines）
繼續有效。新程式請直接 import scrapy_twrh.signals。
'''
from scrapy_twrh.signals import parse_success, parse_error  # noqa: F401
