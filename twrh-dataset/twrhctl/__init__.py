'''twrhctl：twrh-dataset 的無 Django 指令入口（S6／arch 4f，2026-09-26）。

    poetry run python -m twrhctl <command> [args...]

Phase 4 之後 DB 已退場（RDS 2026-09-25 destroy），Django 只剩 management command 的
CLI 殼、timezone／settings 小工具與 export 的 DB 分支。本套件把 flow／出貨實際用到的
指令以同名、同參數、同輸出重寫在純 python 上：

  - 指令外殼：`twrhctl.base.BaseCommand`（介面同 Django 的 BaseCommand：add_arguments／
    handle／CommandError），各指令由 django/*/management/commands/ 逐支搬過來，只留
    檔案時代的分支——DB 分支（house_db()／queue DB 記帳）一律拒跑。
  - 時間：`twrhctl.tz`（Asia/Taipei；Django timezone.localtime／make_aware 的等價物）。
  - 設定：只讀環境變數（.env 由本檔載入，真環境變數優先，與 Django settings 同規則）。

平行期（10/1 前）flow 的 `nodjango` advisory stage 以兩條路徑對同一天逐項比對
（`twrhctl shadowcheck`）；一致即切入口、Django 退休。本行程內**不得載入 django**——
`python -m twrhctl` 結束前會斷言 sys.modules 裡沒有它。
'''
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))   # twrh-dataset/
DJANGO_DIR = os.path.join(BASE, 'django')   # rental／crawlerrequest 純模組住這裡（歷史佈局）

if DJANGO_DIR not in sys.path:
    sys.path.insert(0, DJANGO_DIR)


def _load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # 同 Django settings：repo 根的 .env；真環境變數（task def／SSM）優先
    load_dotenv(os.path.join(BASE, '.env'))


def _init_sentry():
    dsn = os.environ.get('SENTRY_DSN')
    if not dsn:
        return
    import sentry_sdk
    sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1, profiles_sample_rate=0.1)


_load_env()
_init_sentry()
