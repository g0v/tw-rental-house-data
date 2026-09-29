'''twrh-dataset 的無 DB 測試矩陣（S6：由舊 django/crawlerrequest/tests.py 移植）。

    cd twrh-dataset
    env -u PYTHONPATH .venv/bin/python -m unittest discover -s tests -t . -v

Django 與 PostgreSQL 已退場，這裡全是 plain unittest：暫存目錄＋環境變數
（TWRH_ARTIFACT_DIR／TWRH_RAW_*／TWRH_MANIFEST_DIR／TWRH_TARGET_DATE…）指向 temp，
不碰 S3、不打 591。

sys.path：`crawler`／`flow`／`tools`／`twrhctl` 住 twrh-dataset 根目錄，`rental`／
`crawlerrequest` 住 twrh-dataset/django（歷史目錄名）。venv 的 .pth 會把**主 checkout**
的 twrh-dataset 放在 sys.path 尾端；這裡把本 checkout 的兩個目錄插到最前面，
worktree 裡跑的就是 worktree 的碼。（django/ 目錄有 __init__.py，所以根目錄在前時
`import django` 會解析成它——任何人 import django 都是 bug，test_flow_tools 另有
子行程斷言。）
'''
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))   # twrh-dataset/
DJANGO_DIR = os.path.join(ROOT, 'django')

for _path in (DJANGO_DIR, ROOT):
    while _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)

# spider／pipeline 的 log 在測試裡只是雜訊（斷言不看 log）
import logging  # noqa: E402
logging.disable(logging.CRITICAL)
