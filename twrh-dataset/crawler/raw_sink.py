'''raw 直寫 scratch（architecture-roadmap 3-1，案 B 的爬取側）。

pipeline 收到 RawHouseItem 時，除了寫 DB（雙寫對帳期保留，cutover 後
停寫），同步落一份到 scratch：

    <TWRH_RAW_SCRATCH_DIR>/<vendor>/<date>/<house_id>.<kind>.html

多 worker 佈局＝方案 A（2026-09-03 拍板）：worker 各自寫 EFS scratch
（同檔重爬＝覆寫，與 DB 語意一致），收尾由單一 finalize（rawpack）打包成
raw/<vendor>/<date>.tar.zst＋index——一日一檔、完成判據純粹。
crash 後 scratch 殘留＝重跑覆蓋即可。

檔名 kind 沿 rawoffload 月包慣例（detail/list），日期分桶吃
TWRH_TARGET_DATE（與 queue 同一套 pin）。
'''
import os

DEFAULT_SCRATCH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', 'raws', 'scratch')


def enabled():
    return os.environ.get('TWRH_RAW_SINK', '1') == '1'


def scratch_dir():
    return os.environ.get('TWRH_RAW_SCRATCH_DIR', DEFAULT_SCRATCH)


def day_dir(vendor_name, date_str, base=None):
    return os.path.join(base or scratch_dir(), vendor_name, date_str)


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
