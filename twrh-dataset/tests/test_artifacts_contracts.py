'''資料契約（rental/contracts.py）、分區打包（rental/artifacts.py＋twrhctl artifactpack）、
vendor 登錄、tools/backfill_vendor_extra。'''
import importlib.util
import os
import unittest
from datetime import timedelta

from tests.helpers import (ROOT_DIR, TEST_DATE, VENDOR_NAME, TempEnvTestCase, pack, run_command,
                           write_shard)


def _now():
    from rental import tz
    return tz.now()


class ContractTests(unittest.TestCase):
    '''normalized 契約：指紋是雜湊、enum 落 int、座標拆 lat/lng、author 只留雜湊。'''

    def test_list_fingerprint_hash_only_price_title(self):
        from rental import contracts
        fp = contracts.list_fingerprint({'price': '15,000', 'title': 'A', 'update_time': '3小時內'})
        self.assertEqual(fp, contracts.list_fingerprint({'price': '15,000', 'title': 'A', 'update_time': '1天內'}))
        self.assertNotEqual(fp, contracts.list_fingerprint({'price': '16,000', 'title': 'A'}))
        self.assertEqual(len(fp), 16)
        self.assertNotIn('A', fp)

    def test_closure_item_is_detected(self):
        from rental import contracts
        closed = {'vendor': VENDOR_NAME, 'vendor_house_id': 'h', 'deal_status': 1}
        self.assertTrue(contracts.is_closure(closed))
        self.assertFalse(contracts.is_closure({**closed, 'deal_status': 0}))
        self.assertFalse(contracts.is_closure({**closed, 'monthly_price': 1}))   # 解析列
        self.assertFalse(contracts.is_deal_event(closed))

    def test_stub_and_parsed_rows_are_normalized(self):
        from rental import contracts, enums
        now = _now()
        stub = contracts.list_stub('591', 'h1', TEST_DATE, 'run', now, 'abcd', {
            'top_region': enums.TopRegionType.台北市, 'monthly_price': 15000,
            'property_type': enums.PropertyType.獨立套房, 'title': '不該落地'})
        self.assertEqual(stub['top_region'], int(enums.TopRegionType.台北市))
        self.assertNotIn('title', stub)
        self.assertEqual(stub['stub_version'], contracts.LIST_STUB_VERSION)
        row = contracts.parsed_row('591', 'h1', TEST_DATE, 'run', now, '2.4.0', {
            'rough_coordinate': (25.03, 121.56), 'author': '0912345678',
            'contact': enums.ContactType.屋主, 'imgs': ['a', 'b'],
            'deal_status': enums.DealStatusType.OPENED})
        self.assertEqual((row['rough_lat'], row['rough_lng']), (25.03, 121.56))
        self.assertNotIn('author', row)
        self.assertEqual(len(row['author_key']), 16)
        coerced = contracts.coerce_row(row, contracts.PARSED_FIELDS)
        self.assertEqual(coerced['imgs'], '["a", "b"]')
        self.assertEqual(coerced['crawled_at'], now)
        self.assertIsNone(coerced['vendor_extra'])                  # 404／拒解析列：NULL
        extra = contracts.parsed_row('591', 'h1', TEST_DATE, 'run', now, '2.4.0', {},
                                     vendor_extra={'b': 1, 'a': '甲'})['vendor_extra']
        self.assertEqual(extra, '{"a": "甲", "b": 1}')              # 整份 dict、鍵排序、不轉義
        self.assertEqual(contracts.PARSED_VERSION, 2)
        self.assertEqual(set(coerced), {name for name, _ in contracts.PARSED_FIELDS})
        contracts.arrow_schema(contracts.PARSED_FIELDS)   # pyarrow 可建

    def test_snapshot_and_latest_field_sets(self):
        from rental import contracts, latest
        names = [n for n, _ in contracts.SNAPSHOT_FIELDS]
        self.assertEqual(len(names), len(set(names)))
        for carry, _ in contracts.SNAPSHOT_CARRY_FIELDS:
            self.assertIn(carry, names)
        self.assertNotIn('run', names)
        self.assertEqual([n for n, _ in latest.LATEST_FIELDS], [n for n in names if n != 'vendor_extra'])


class ArtifactPackTests(TempEnvTestCase):
    '''artifactpack：shard → 一輪一檔；parsed 去重後爬者勝；同 run 重打聯集；不同 run 各自成檔；
    孤兒日期也打。'''

    def test_list_stubs_one_file_per_run_and_union_on_rerun(self):
        from rental import artifacts
        t = _now().isoformat()
        write_shard('list', [
            {'vendor_house_id': 'a', 'seen_at': t, 'fingerprint': 'f1', 'monthly_price': 1},
            {'vendor_house_id': 'b', 'seen_at': t, 'fingerprint': 'f2'}])
        pack(self, 'list')
        write_shard('list', [{'vendor_house_id': 'c', 'seen_at': t, 'fingerprint': 'f3'}], run='sweep-0500')
        write_shard('list', [{'vendor_house_id': 'd', 'seen_at': t, 'fingerprint': 'f4'}])  # 同 run 重跑：聯集
        pack(self, 'list')
        files = artifacts.list_partition_files('591', TEST_DATE)
        self.assertEqual([os.path.basename(p) for p in files], ['run.jsonl.zst', 'sweep-0500.jsonl.zst'])
        rows = list(artifacts.read_list_stubs('591', TEST_DATE))
        self.assertEqual(sorted(r['vendor_house_id'] for r in rows), ['a', 'b', 'c', 'd'])
        self.assertEqual(next(r for r in rows if r['vendor_house_id'] == 'a')['monthly_price'], 1)
        self.assertFalse(os.path.exists(artifacts.scratch_dir('list', '591', TEST_DATE)))

    def test_local_partitions_lists_packed_runs(self):
        from rental import artifacts
        t = _now().isoformat()
        write_shard('list', [{'vendor_house_id': 'a', 'seen_at': t, 'fingerprint': 'f'}])
        write_shard('list', [{'vendor_house_id': 'b', 'seen_at': t, 'fingerprint': 'f'}], run='sweep-0800')
        pack(self, 'list')
        self.assertEqual([(v, r) for v, r, _ in artifacts.local_partitions('list', TEST_DATE)],
                         [('591', 'run'), ('591', 'sweep-0800')])
        self.assertEqual(artifacts.local_partitions('parsed', TEST_DATE), [])

    def test_parsed_parquet_dedups_latest_and_packs_orphans(self):
        import pyarrow.parquet as pq
        from rental import artifacts
        early = (_now() - timedelta(hours=1)).isoformat()
        late = _now().isoformat()
        write_shard('parsed', [
            {'vendor_house_id': 'a', 'crawled_at': late, 'monthly_price': 20000,
             'imgs': ['x'], 'top_region': 17},
            {'vendor_house_id': 'a', 'crawled_at': early, 'monthly_price': 10000},
            {'vendor_house_id': 'b', 'crawled_at': late}])
        write_shard('parsed', [{'vendor_house_id': 'z', 'crawled_at': late}],
                    date_str='2026-01-14', run='sweep-2300')
        out = pack(self, 'parsed')
        self.assertIn('orphan parsed scratch', out)
        table = pq.read_table(artifacts.partition_path('parsed', '591', TEST_DATE, 'run'))
        self.assertEqual(table.num_rows, 2)
        a = table.to_pylist()[0]
        self.assertEqual((a['vendor_house_id'], a['monthly_price'], a['imgs']), ('a', 20000, '["x"]'))
        self.assertEqual(table.schema.field('crawled_at').type.tz, 'UTC')
        self.assertTrue(os.path.exists(artifacts.partition_path('parsed', '591', '2026-01-14', 'sweep-2300')))

    def test_deal_event_contract_and_pack(self):
        from rental import artifacts, contracts, tz
        from datetime import datetime
        deal_time = tz.make_aware(datetime(2026, 1, 14))
        # key 組＝scrapy_twrh deal_mixin 實際 yield 的（含 vendor_house_url；2026-09-12 首夜漏這個 key）
        item = {'vendor': VENDOR_NAME, 'vendor_house_id': 'h1', 'vendor_house_url': 'u',
                'deal_status': 2, 'deal_time': deal_time, 'n_day_deal': 3}
        self.assertTrue(contracts.is_deal_event(item))
        self.assertTrue(contracts.is_deal_event({k: v for k, v in item.items() if k != 'vendor_house_url'}))
        self.assertFalse(contracts.is_deal_event({**item, 'monthly_price': 1}))   # detail 列
        self.assertFalse(contracts.is_deal_event({**item, 'deal_status': 0}))
        row = contracts.deal_event_row('591', 'h1', TEST_DATE, 'run', _now(), deal_time, 3)
        self.assertEqual(set(row), {name for name, _ in contracts.DEAL_EVENT_FIELDS})
        write_shard('deals', [{k: v for k, v in row.items() if k not in ('vendor', 'date', 'run')}])
        pack(self, 'deals')
        rows = artifacts.read_deal_events('591', TEST_DATE)
        self.assertEqual([(r['vendor_house_id'], r['deal_time'], r['n_day_deal']) for r in rows],
                         [('h1', deal_time, 3)])
        self.assertTrue(os.path.exists(artifacts.partition_path('deals', '591', TEST_DATE, 'run')))

    def test_nothing_to_pack_and_bad_args(self):
        self.assertIn('nothing to pack', pack(self, 'parsed'))
        self.assertEqual(run_command('artifactpack', '--tree', 'list', '--date', '2026/01/15')[0], 1)
        self.assertEqual(run_command('artifactpack', '--tree', 'list', '--reupload')[0], 1)   # 沒 bucket
        self.assertEqual(run_command('artifactpack', '--tree', 'nope')[0], 2)                 # argparse


class VendorRegistryTests(unittest.TestCase):
    def test_registry_is_the_vendor_table(self):
        from rental import vendors
        self.assertEqual([(ref.id, ref.name) for ref in vendors.REGISTRY],
                         [(1, '591 租屋網'), (2, '好房網'), (3, '蟹居網')])
        self.assertEqual(vendors.get(VENDOR_NAME), vendors.VendorRef(1, VENDOR_NAME))
        self.assertEqual(vendors.get(VENDOR_NAME).pk, 1)
        self.assertEqual(vendors.by_short('591').name, VENDOR_NAME)
        self.assertIsNone(vendors.by_short('nope'))
        with self.assertRaises(LookupError):
            vendors.get('nope')


class BackfillVendorExtraTests(unittest.TestCase):
    '''tools/backfill_vendor_extra 的純函數：加欄／只補 NULL／force／404 關閉列不補。'''

    def test_fill_vendor_extra(self):
        import pyarrow as pa
        spec = importlib.util.spec_from_file_location(
            'backfill_vendor_extra', os.path.join(ROOT_DIR, 'tools', 'backfill_vendor_extra.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        table = pa.table({
            'vendor_house_id': ['a', 'b', 'c', 'd'],
            'deal_status': [0, 0, 1, 1],
            'monthly_price': [10000, 12000, None, 9000],   # c＝404 關閉列（全 NULL）、d＝成交但有值
            'floor_ping': [10.0, 12.0, None, 9.0],
            'top_region': [1, 1, None, 1],
            'imgs': ['[]', '[]', None, '[]'],
            'parsed_version': [1, 1, 1, 1],
        })
        extras = {'a': '{"k": 1}', 'c': '{"k": 3}', 'd': '{"k": 4}'}
        out, filled = mod.fill_vendor_extra(table, extras)
        self.assertEqual(filled, 2)                                      # a、d；b 沒 raw、c 關閉列
        self.assertEqual(out.column_names.index('vendor_extra'), out.column_names.index('parsed_version') - 1)
        self.assertEqual(out.column('vendor_extra').to_pylist(), ['{"k": 1}', None, None, '{"k": 4}'])
        again, filled2 = mod.fill_vendor_extra(out, {'a': '{"k": 9}', 'b': '{"k": 2}'})
        self.assertEqual((filled2, again.column('vendor_extra').to_pylist()[:2]), (1, ['{"k": 1}', '{"k": 2}']))
        forced, filled3 = mod.fill_vendor_extra(out, {'a': '{"k": 9}'}, force=True)
        self.assertEqual((filled3, forced.column('vendor_extra').to_pylist()[0]), (1, '{"k": 9}'))


if __name__ == '__main__':
    unittest.main()
