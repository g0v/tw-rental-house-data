'''manifest 的檔案層（純函數，無 Django／DB 相依——3-3 零雲相依配套）。

builders（讀 DB 算 manifest）在 manifests.py；這裡只有路徑、讀寫、
dot-path 取值——貢獻者 `aws s3 sync` 拉回 manifests/ 分區後，
不建 PostGIS 也能跑斷言引擎（tools/quality_offline.py）。
'''
import json
import os

SCHEMA_VERSION = 1
STAGES = ('list', 'detail', 'deals', 'snapshot')

DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', '..', 'manifests')


def manifest_dir():
    return os.environ.get('TWRH_MANIFEST_DIR', DEFAULT_DIR)


def manifest_path(date_str, stage, base_dir=None):
    return os.path.join(base_dir or manifest_dir(), date_str, stage + '.json')


def write_manifest(manifest, base_dir=None):
    path = manifest_path(manifest['date'], manifest['stage'], base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, default=str)
    return path


def load_manifest(date_str, stage, base_dir=None):
    try:
        with open(manifest_path(date_str, stage, base_dir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def get_metric(manifest, dotted):
    '''以 "queue.dead_ratio"、"dist.median_floor" 這類 dot path 取值。'''
    node = manifest
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
