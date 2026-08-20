'''自訂 scrapy 訊號（docs/dx-roadmap.md 2-1）。

parser_wrapper 會吞掉 callback 的例外，scrapy 原生的 spider_error 因此永遠不會發，
熔斷 extension 收不到訊號 —— 所以由 parser_wrapper / pipeline 主動送這兩個訊號。
發版時將隨 2.5-1 一併上移至 scrapy-tw-rental-house。
'''

# 一個 request 的 parse 正常完成（persist queue 的該筆 request 已刪除）
parse_success = object()

# parse 或 pipeline 丟出例外（該筆 request 保留在 queue，等 statscheck 收屍）
parse_error = object()
