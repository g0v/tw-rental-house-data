#!/bin/bash
# 開發 scrapy-tw-rental-house 時，把本地 core 以 editable 模式蓋進本專案 venv，
# 讓 parser 改動不必先 poetry publish 就能在真 pipeline 驗證（docs/dx-roadmap.md 0-3）。
#
# 還原成 lock 檔的發布版：poetry install --sync
set -e
cd "$(dirname "$0")"
# --no-deps：依賴已由發布版帶入 venv（含自訂 source 的 paddlepaddle），
# 讓 pip 解析依賴反而會因 PyPI 上找不到 paddle 的版本而失敗
poetry run pip install -e ../scrapy-tw-rental-house --no-deps
poetry run python -c "import scrapy_twrh; print('scrapy_twrh →', scrapy_twrh.__file__)"
