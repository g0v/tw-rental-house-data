'''enums 單一來源（dx 4-1）：直接 re-export 已安裝套件的定義。

本檔曾是 scrapy_twrh.spiders.enums 的複本（連同 data/tw_regions.json），
兩份已實際漂移過（峨嵋／峨眉順序相反→SubRegionType canonical 不一致）。
自 scrapy-tw-rental-house 2.2.4 起兩邊內容拉齊，此處收斂為 re-export——
enum 整數值出現在已發布資料集，只能新增不能重編號，維護處只剩套件一處。
'''
from scrapy_twrh.spiders.enums import *  # noqa: F401,F403
