'''raw 檔案佈局的單一定義（3-1）：scratch 路徑、vendor 短名、日包目錄。

住在 django 樹是因為兩類行程都要用：manage.py（rawpack）天生只看得到
django app；scrapy 行程（pipeline 經 crawler/raw_sink 薄轉發）由
general_settings 把 django/ 加進 sys.path。反過來放 crawler/ 會讓
manage.py import 不到——image 是 poetry install --no-root，crawler
套件不在 site-packages（2026-09-04 首跑實踩）。
'''
import os

# twrh-dataset 根目錄（rental/ 在 django/ 下一層）
_BASE = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..')

DEFAULT_SCRATCH = os.path.join(_BASE, 'raws', 'scratch')
DEFAULT_RAW_DIR = os.path.join(_BASE, 'raws')


def enabled():
    return os.environ.get('TWRH_RAW_SINK', '1') == '1'


def scratch_dir():
    return os.environ.get('TWRH_RAW_SCRATCH_DIR', DEFAULT_SCRATCH)


def raw_dir():
    return os.environ.get('TWRH_RAW_DIR', DEFAULT_RAW_DIR)


def vendor_dirname(vendor_name):
    '''目錄／S3 key 用的 vendor 短名：取首個 token（'591 租屋網' → '591'），
    對齊 housekeep 月包既有的 raw/591/ 佈局，也避開 key 帶空白的麻煩。'''
    return vendor_name.split()[0]


def day_dir(vendor_name, date_str, base=None):
    return os.path.join(
        base or scratch_dir(), vendor_dirname(vendor_name), date_str)


def write_raw(vendor_name, date_str, house_id, kind, text):
    '''寫一頁 raw 到 scratch。tmp＋rename 保原子性（多 worker 同檔互撞時
    後寫者勝，與 DB 覆寫語意一致）。'''
    target_dir = day_dir(vendor_name, date_str)
    os.makedirs(target_dir, exist_ok=True)
    name = '{}.{}.html'.format(house_id, kind)
    path = os.path.join(target_dir, name)
    tmp = '{}.tmp.{}'.format(path, os.getpid())
    data = text.encode('utf-8') if isinstance(text, str) else text
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)
    return path
