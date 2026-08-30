"""UI 資料列產生器（export-automation-plan P4）：把出貨 zip 寫進
ui-next/src/data/stats/<year>.json 的 monthly/quarterly/annual 列。

counts 取自 zip 內建的 metadata json（{"_total": N, "<vendor>": N}，
591 租屋網 → UI 的 "591"）；size 取 zip 實檔。同 (period, time, type) 的列
upsert——重跑無害。quality_issue 標記**永遠人工**：本工具只在 --quality-issue
明示時寫入，否則保留既有值。

用法（publish.sh 步驟 4；手動亦可）：
  python tools/publish_ui_stats.py --stats-dir ../ui-next/src/data/stats \
      --period monthly --time 8 --year 2026 \
      --zip "datas/[202608][CSV][Raw] TW-Rental-Data.zip" \
      --zip "datas/[202608][CSV][Deduplicated] TW-Rental-Data.zip" \
      [--json-zip "datas/[202608][JSON][Raw] TW-Rental-Data.zip"] \
      [--quality-issue <id>] [--comment <markdown>]
"""
import argparse
import io
import json
import os
import zipfile

TYPE_BY_KIND = {'Raw': '原始資料', 'Deduplicated': '消除重複住宅'}
VENDOR_UI_NAME = {'591 租屋網': '591'}


def zip_kind(path):
    base = os.path.basename(path)
    for kind in TYPE_BY_KIND:
        if f'[{kind}]' in base:
            return kind
    raise SystemExit(f'無法從檔名判別 Raw/Deduplicated: {base}')


def inner_data_size(path, suffix):
    """UI 的 size_byte 慣例＝解壓後資料檔大小（非 zip 檔大小）；空 zip 回 0。"""
    with zipfile.ZipFile(path) as z:
        return sum(i.file_size for i in z.infolist()
                   if i.filename.endswith(suffix) and '編碼表' not in i.filename)


def zip_counts(path):
    """讀 zip 內 metadata json；沒有就退回數 CSV 行數。"""
    with zipfile.ZipFile(path) as z:
        metas = [n for n in z.namelist()
                 if n.endswith('.json') and '編碼表' not in n]
        if metas:
            meta = json.loads(z.read(metas[0]))
            total = meta.get('_total')
            sources = [
                {'name': VENDOR_UI_NAME.get(k, k), 'count': v}
                for k, v in meta.items() if k != '_total']
            if total is not None:
                return total, sources
        csvs = [n for n in z.namelist()
                if n.endswith('.csv') and '編碼表' not in n]
        assert len(csvs) == 1, f'zip 內 CSV 數量異常: {csvs}'
        with z.open(csvs[0]) as f:
            total = sum(1 for _ in io.TextIOWrapper(f, 'utf-8')) - 1
        return total, [{'name': '591', 'count': total}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stats-dir', required=True)
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--period', choices=['monthly', 'quarterly', 'annual'],
                    required=True)
    ap.add_argument('--time', required=True,
                    help='monthly=月份、quarterly=季次、annual 給空字串')
    ap.add_argument('--zip', action='append', required=True, dest='zips')
    ap.add_argument('--json-zip', help='附掛到「原始資料」列的 JSON 格式 zip')
    ap.add_argument('--quality-issue')
    ap.add_argument('--comment')
    args = ap.parse_args()

    stats_path = os.path.join(args.stats_dir, f'{args.year}.json')
    with open(stats_path) as f:
        doc = json.load(f)
    rows = doc.setdefault(args.period, [])

    for path in args.zips:
        kind = zip_kind(path)
        row_type = TYPE_BY_KIND[kind]
        total, sources = zip_counts(path)
        files = [{'format': 'csv', 'size_byte': inner_data_size(path, '.csv'),
                  'download_url': {'isS3': True}}]
        if kind == 'Raw' and args.json_zip:
            json_size = inner_data_size(args.json_zip, '.json')
            if json_size:
                files.append({'format': 'json', 'size_byte': json_size,
                              'download_url': {'isS3': True}})
            else:
                print(f'json zip 內無資料檔，跳過 json 列: {args.json_zip}')

        existing = next(
            (r for r in rows
             if r.get('time') == args.time and r.get('type') == row_type),
            None)
        row = existing if existing is not None else {}
        row.update({
            'schema_ver': '1.0.0',
            'data_ver': '0.3',
            'time': args.time,
            'type': row_type,
            'total_count': total,
            'sources': sources,
            'files': files,
        })
        if args.comment is not None:
            row['comment'] = args.comment
        else:
            row.setdefault('comment', '')
        if args.quality_issue:
            row['quality_issue'] = args.quality_issue
        if existing is None:
            rows.append(row)
        print(f'{args.period} time={args.time} {row_type}: '
              f'count={total} files={len(files)}'
              + (f' quality_issue={row.get("quality_issue")}'
                 if row.get('quality_issue') else ''))

    with open(stats_path, 'w') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'updated {stats_path}')


if __name__ == '__main__':
    main()
