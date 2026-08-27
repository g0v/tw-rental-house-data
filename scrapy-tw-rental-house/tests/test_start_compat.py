"""scrapy 2.13+ 的 async start() 與舊版 start_requests() 相容性。

scrapy 2.18 起不再 fallback 到 deprecated 的 start_requests()——
少了 start() 時 spider 會零請求靜默收單（2026-08-28 全量首排程實際踩到）。
"""
import asyncio
import inspect

from scrapy_twrh.spiders.rental_spider import RentalSpider
from scrapy_twrh.spiders.rental591 import Rental591Spider


def test_start_is_async_generator():
    assert inspect.isasyncgenfunction(RentalSpider.start)


def test_start_yields_same_requests_as_start_requests():
    async def collect():
        spider = Rental591Spider(target_cities=['金門縣'])
        return [item async for item in spider.start()]

    async_items = asyncio.run(collect())
    sync_items = list(Rental591Spider(target_cities=['金門縣']).start_requests())

    assert len(async_items) == len(sync_items) == 1
    assert async_items[0].url == sync_items[0].url
