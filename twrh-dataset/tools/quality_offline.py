'''quality_offline：離線斷言引擎（architecture-roadmap 3-3 零雲相依）。

不需 PostGIS、不需 Django 設定——sync 回來的 manifests/ 分區＋repo 的
quality/assertions.yaml 就能重跑品質斷言（同一顆引擎，qualitycheck 的
DB-free 入口）。新貢獻者的 pipeline 迴路：

    ./tools/sync-dev-data.sh            # 拉 manifests/（與最近的 raw 日包）
    poetry run python tools/quality_offline.py --date 2026-09-03

exit code 同 qualitycheck：0＝綠、1＝有硬斷言失敗。
'''
import argparse
import os
import sys
from datetime import date as date_cls

BASE = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(BASE, '..', 'django'))

from crawlerrequest import quality  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description='Run quality assertions against synced manifests, no DB needed')
    parser.add_argument('--date', default=date_cls.today().isoformat())
    parser.add_argument('--assertions', help='assertions.yaml 路徑覆寫')
    parser.add_argument('--manifest-dir', help='manifests 目錄覆寫')
    options = parser.parse_args()

    results = quality.evaluate(
        options.date, assertions_path=options.assertions,
        base_dir=options.manifest_dir)
    for r in results:
        print(r.line())
    failures = [r for r in results if not r.ok and not r.advisory]
    advisories = [r for r in results if not r.ok and r.advisory]
    print('{}: {} hard failure(s), {} advisory'.format(
        options.date, len(failures), len(advisories)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
