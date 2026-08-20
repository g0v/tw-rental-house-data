# 空的 scrapy settings 模組。
# CLI 在 import parser 前把 SCRAPY_SETTINGS_MODULE 指到這裡，
# 避免從某個 scrapy 專案目錄執行時，get_project_settings() 連帶載入
# 該專案的 settings（例如 twrh-dataset 的 crawler.settings 會 django.setup()）。
