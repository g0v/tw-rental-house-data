'''自訂 scrapy 訊號（docs/dx-roadmap.md 2-1）。

營運端（twrh-dataset）的 parser_wrapper 會吞掉 callback 的例外，scrapy 原生的
spider_error 因此永遠不會發，熔斷 extension 收不到訊號 —— 所以由包住 parser 的
那一層（parser_wrapper／pipeline）主動送這兩個訊號。直接使用本套件、沒有自己
包 parser 的 spider，例外會自然逃出 callback，熔斷會改聽 spider_error。
'''

# 一個 request 的 parse 正常完成
parse_success = object()

# parse 或 pipeline 丟出例外
parse_error = object()
