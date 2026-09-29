'''snapshot fold（rental/snapshot.py）、成交段（rental/deals.py）、總表（rental/latest.py）
與 twrhctl snapshotfold／latestfold。'''
import os
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from tests.helpers import (TEST_DATE, TempEnvTestCase, check_command, pack, run_command,
                           snapshot_row, write_shard)


class SnapshotFoldTests(unittest.TestCase):
    '''fold 純函數：detail／list／carry 三種來源、carry 欄遞推、DEAL sticky、deals 事件優先、
    已關閉且無訊號不攜帶。'''

    D1, D2 = '2026-01-15', '2026-01-16'

    def stub(self, hid, at, fp='f1', price=10000):
        return {'vendor_house_id': hid, 'seen_at': at, 'fingerprint': fp, 'monthly_price': price}

    def parsed(self, hid, at, status=0, price=10000):
        return {'vendor_house_id': hid, 'crawled_at': at, 'deal_status': status,
                'monthly_price': price, 'floor_ping': 12.5}

    def test_back_in_list_reopens_closed_and_dealt(self):
        '''重新出現在 list 且今日無關閉訊號＝在架的正面觀測，狀態要回 OPENED（2026-09-16：
        55 戶標成 NOT_FOUND 卻出現在今日 list）。DEAL 也一樣要回：sticky 只擋 detail 404。'''
        from rental.snapshot import fold, OPENED, NOT_FOUND, DEAL
        day1 = fold([], [self.stub('gone', 'T1'), self.stub('sold', 'T1')],
                    [self.parsed('gone', 'T1d'), self.parsed('sold', 'T1d')], [], self.D1)
        day2 = fold(day1, [], [{'vendor_house_id': 'gone', 'deal_status': NOT_FOUND}],
                    [{'vendor_house_id': 'sold', 'deal_status': DEAL,
                      'deal_time': 'T2', 'n_day_deal': 3}], self.D2)
        by = {r['vendor_house_id']: r for r in day2}
        self.assertEqual((by['gone']['deal_status'], by['sold']['deal_status']), (NOT_FOUND, DEAL))

        day3 = fold(day2, [self.stub('gone', 'T3'), self.stub('sold', 'T3')], [], [], '2026-01-17')
        by = {r['vendor_house_id']: r for r in day3}
        for hid in ('gone', 'sold'):
            self.assertEqual(by[hid]['deal_status'], OPENED, hid)
            self.assertIsNone(by[hid]['deal_time'], hid)
            self.assertIsNone(by[hid]['n_day_deal'], hid)
            self.assertIsNone(by[hid]['deal_source'], hid)
            self.assertEqual(by[hid]['source'], 'list', hid)

    def test_detail_none_does_not_erase_known_values(self):
        '''2026-09-19 拍板：parsed 列的 None 不蓋既有值；狀態欄與 crawled_at 照舊由 detail 決定。'''
        from rental.snapshot import fold
        stub = {**self.stub('a', 'T1'), 'rough_address': '大安區-臨江街', 'floor_ping': 12.5}
        day1 = fold([], [stub], [{**self.parsed('a', 'T1d'), 'rough_address': None,
                                  'vendor_house_url': None, 'has_parking': True,
                                  'monthly_parking_fee': 0, 'deal_time': None}], [], self.D1)
        a = day1[0]
        self.assertEqual((a['rough_address'], a['has_parking'], a['source']), ('大安區-臨江街', True, 'detail'))
        day2 = fold(day1, [], [{**self.parsed('a', 'T2d', price=11000), 'has_parking': None,
                                'rough_address': None, 'deal_time': None, 'n_day_deal': None}], [], self.D2)
        a = day2[0]
        self.assertEqual((a['monthly_price'], a['has_parking'], a['rough_address'], a['last_detail_at']),
                         (11000, True, '大安區-臨江街', 'T2d'))
        self.assertIsNone(a['deal_time'])

    def test_list_price_change_recomputes_per_ping(self):
        from rental.snapshot import fold
        day1 = fold([], [self.stub('a', 'T1')],
                    [{**self.parsed('a', 'T1d'), 'monthly_management_fee': 500,
                      'monthly_parking_fee': 0, 'per_ping_price': 840.0}], [], self.D1)
        self.assertEqual(day1[0]['per_ping_price'], 840.0)
        day2 = fold(day1, [{**self.stub('a', 'T2', fp='f2', price=12000), 'per_ping_price': 960.0}],
                    [], [], self.D2)
        a = day2[0]
        self.assertEqual((a['monthly_price'], a['source']), (12000, 'list'))
        self.assertAlmostEqual(a['per_ping_price'], (12000 + 500) / 12.5)   # 不是 list 的 960
        day1b = fold([], [{**self.stub('b', 'T1', price=5000), 'per_ping_price': 500.0}], [], [], self.D1)
        self.assertEqual(day1b[0]['per_ping_price'], 500.0)                 # 坪數未知：留 list 的

    def test_list_day_rebuilds_apt_code_from_carried_balcony_bath(self):
        '''2026-09-20：list 頁只給房／廳，陽台／衛浴沿用列上攜帶的值重組格局編碼。'''
        from rental.snapshot import fold
        day1 = fold([], [self.stub('a', 'T1')],
                    [{**self.parsed('a', 'T1d'), 'n_balcony': 2, 'n_bath_room': 2,
                      'n_bed_room': 3, 'n_living_room': 2, 'apt_feature_code': '02020302'}],
                    [], self.D1)
        self.assertEqual(day1[0]['apt_feature_code'], '02020302')
        day2 = fold(day1, [{**self.stub('a', 'T2', fp='f2'), 'n_bed_room': 2, 'n_living_room': 1,
                            'apt_feature_code': '00000201'}], [], [], self.D2)
        self.assertEqual((day2[0]['apt_feature_code'], day2[0]['n_balcony'], day2[0]['n_bath_room'],
                          day2[0]['n_bed_room']), ('02020201', 2, 2, 2))
        day3 = fold(day2, [self.stub('a', 'T3', fp='f3')], [], [], '2026-01-17')
        self.assertEqual(day3[0]['apt_feature_code'], '02020201')            # list 沒給房廳：碼不動
        day1b = fold([], [{**self.stub('b', 'T1'), 'n_bed_room': 3, 'n_living_room': 2,
                           'apt_feature_code': '00000302'}], [], [], self.D1)
        self.assertEqual(day1b[0]['apt_feature_code'], '00000302')

    def test_same_day_404_wins_status_but_list_fields_carry(self):
        from rental.snapshot import fold, NOT_FOUND
        day1 = fold([], [self.stub('a', 'T1')], [self.parsed('a', 'T1d')], [], self.D1)
        day2 = fold(day1, [self.stub('a', 'T2', fp='f2', price=9000)],
                    [{'vendor_house_id': 'a', 'deal_status': NOT_FOUND}], [], self.D2)
        a = day2[0]
        self.assertEqual((a['deal_status'], a['monthly_price'], a['source'], a['last_seen_at'],
                          a['days_absent'], a['last_fingerprint'], a['floor_ping']),
                         (NOT_FOUND, 9000, 'list', 'T2', 0, 'f2', 12.5))
        self.assertAlmostEqual(a['per_ping_price'], 9000 / 12.5)

    def test_returning_house_recovers_from_latest_row(self):
        from rental.snapshot import fold, NOT_FOUND, OPENED
        day1 = fold([], [self.stub('a', 'T1')], [self.parsed('a', 'T1d')], [], self.D1)
        day2 = fold(day1, [], [{'vendor_house_id': 'a', 'deal_status': NOT_FOUND}], [], self.D2)
        self.assertEqual(day2[0]['deal_status'], NOT_FOUND)
        day3 = fold(day2, [], [], [], '2026-01-17')
        self.assertEqual(day3, [])                                   # 關閉且無訊號：不攜帶
        blank = fold(day3, [self.stub('a', 'T4', price=9500)], [], [], '2026-01-18')[0]
        self.assertEqual((blank['floor_ping'], blank['last_detail_at'], blank['deal_status']), (None, None, OPENED))
        back = fold(day3, [self.stub('a', 'T4', price=9500)], [], [], '2026-01-18',
                    closed_rows={'a': day2[0]})[0]
        self.assertEqual((back['floor_ping'], back['last_detail_at'], back['deal_status'], back['monthly_price'],
                          back['source'], back['days_absent'], back['first_seen_at']),
                         (12.5, 'T1d', OPENED, 9500, 'list', 0, 'T1'))

    def test_day_one_and_day_two_carry_semantics(self):
        from rental import contracts
        from rental.snapshot import fold
        day1 = fold([], [self.stub('a', 'T1'), self.stub('b', 'T1'), self.stub('c', 'T1')],
                    [self.parsed('a', 'T1d'), self.parsed('b', 'T1d')], [], self.D1)
        by = {r['vendor_house_id']: r for r in day1}
        self.assertEqual({k: v['source'] for k, v in by.items()}, {'a': 'detail', 'b': 'detail', 'c': 'list'})
        self.assertEqual((by['a']['last_detail_at'], by['a']['fingerprint_at_last_detail'],
                          by['a']['first_seen_at'], by['a']['days_absent']), ('T1d', 'f1', 'T1', 0))
        self.assertIsNone(by['c']['floor_ping'])
        self.assertEqual(set(by['a']), {name for name, _ in contracts.SNAPSHOT_FIELDS})

        day2 = fold(day1, [self.stub('a', 'T2', fp='f2', price=12000), self.stub('d', 'T2')],
                    [self.parsed('c', 'T2d')], [], self.D2)
        by = {r['vendor_house_id']: r for r in day2}
        self.assertEqual(by['a']['source'], 'list')
        self.assertEqual((by['a']['monthly_price'], by['a']['floor_ping']), (12000, 12.5))
        self.assertEqual((by['a']['last_detail_at'], by['a']['fingerprint_at_last_detail']), ('T1d', 'f1'))
        self.assertEqual((by['a']['last_seen_at'], by['a']['first_seen_at']), ('T2', 'T1'))
        self.assertEqual((by['b']['source'], by['b']['days_absent'], by['b']['last_seen_at']), ('carry', 1, 'T1'))
        self.assertEqual((by['c']['source'], by['c']['last_detail_at'], by['c']['fingerprint_at_last_detail']),
                         ('detail', 'T2d', 'f1'))
        self.assertEqual((by['a']['last_fingerprint'], by['c']['last_fingerprint']), ('f2', 'f1'))
        self.assertEqual((by['d']['source'], by['d']['first_seen_at'], by['d']['date']), ('list', 'T2', self.D2))

    def test_vendor_extra_rides_with_detail_and_carries(self):
        from rental.snapshot import fold
        p = dict(self.parsed('a', 'T1d'), vendor_extra='{"k": 1}')
        day1 = fold([], [self.stub('a', 'T1')], [p], [], self.D1)
        self.assertEqual(day1[0]['vendor_extra'], '{"k": 1}')
        day2 = fold(day1, [self.stub('a', 'T2', price=9000)], [], [], self.D2)
        self.assertEqual((day2[0]['source'], day2[0]['vendor_extra']), ('list', '{"k": 1}'))
        day3 = fold(day2, [], [{'vendor_house_id': 'a', 'crawled_at': 'T3d', 'deal_status': 1}], [], '2026-01-17')
        self.assertEqual((day3[0]['deal_status'], day3[0]['vendor_extra']), (1, '{"k": 1}'))   # 404 不清值
        day4 = fold(day2, [], [dict(self.parsed('a', 'T4d'), vendor_extra='{"k": 2}')], [], '2026-01-18')
        self.assertEqual(day4[0]['vendor_extra'], '{"k": 2}')

    def test_deal_sticky_and_vendor_event_wins(self):
        from rental.snapshot import fold, DEAL, NOT_FOUND
        day1 = fold([], [self.stub('x', 'T1'), self.stub('y', 'T1'), self.stub('z', 'T1')],
                    [self.parsed('x', 'T1d')], [], self.D1)
        day2 = fold(day1, [], [self.parsed('y', 'T2d', status=NOT_FOUND)],
                    [{'vendor_house_id': 'x', 'seen_at': 'T2', 'deal_time': 'D', 'n_day_deal': 3}], self.D2)
        by = {r['vendor_house_id']: r for r in day2}
        self.assertEqual((by['x']['deal_status'], by['x']['deal_time'], by['x']['n_day_deal'], by['x']['deal_source']),
                         (DEAL, 'D', 3, 'deals'))
        self.assertEqual((by['y']['deal_status'], by['y']['deal_source']), (NOT_FOUND, None))
        self.assertEqual((by['z']['source'], by['z']['days_absent']), ('carry', 1))
        day3 = fold(day2, [], [self.parsed('x', 'T3d', status=NOT_FOUND)], [], '2026-01-17')
        by = {r['vendor_house_id']: r for r in day3}
        self.assertEqual(sorted(by), ['x', 'z'])
        self.assertEqual((by['x']['deal_status'], by['x']['deal_source'], by['x']['n_day_deal']), (DEAL, 'deals', 3))
        self.assertEqual(by['z']['days_absent'], 2)

    def test_not_found_closure_row_keeps_last_known_values(self):
        '''pipeline 寫的 404 列（只帶 deal_status）：只改狀態、source 不變、DEAL sticky。'''
        from rental import snapshot
        closure = [{'vendor_house_id': 'gone', 'deal_status': snapshot.NOT_FOUND,
                    'crawled_at': 'T2d', 'monthly_price': None, 'rough_lat': None}]
        prev = snapshot._blank('591', 'gone', '2026-01-14')
        prev.update({'monthly_price': 9000, 'rough_lat': 25.0, 'source': 'detail', 'last_detail_at': 'T1d'})
        today = {r['vendor_house_id']: r for r in snapshot.fold([prev], [], closure, [], TEST_DATE)}
        self.assertEqual((today['gone']['deal_status'], today['gone']['source'],
                          today['gone']['monthly_price'], today['gone']['rough_lat'],
                          today['gone']['last_detail_at']),
                         (snapshot.NOT_FOUND, 'carry', 9000, 25.0, 'T1d'))
        prev['deal_status'] = snapshot.DEAL
        today = {r['vendor_house_id']: r for r in snapshot.fold([prev], [], closure, [], TEST_DATE)}
        self.assertEqual(today['gone']['deal_status'], snapshot.DEAL)


class DealDeriveTests(unittest.TestCase):
    '''成交段（rental/deals.py）：deals 事件勝、inferred 語意、n_day_deal 推導、late deal 補值。'''

    def test_n_day_deal_inferred_uses_taipei_calendar_days(self):
        from datetime import timezone
        from rental.deals import n_day_deal_inferred
        tpe = timezone(timedelta(hours=8))
        first = datetime(2026, 1, 10, 23, 30, tzinfo=tpe)          # 台北 1/10 深夜（UTC 1/10 15:30）
        deal = datetime(2026, 1, 13, 0, 0, tzinfo=tpe)
        self.assertEqual(n_day_deal_inferred(deal, first), 3)
        self.assertEqual(n_day_deal_inferred(deal, first.astimezone(timezone.utc)), 3)
        self.assertEqual(n_day_deal_inferred(first, deal), 0)                    # 倒過來夾 0
        self.assertIsNone(n_day_deal_inferred(None, first))
        self.assertIsNone(n_day_deal_inferred('2026-01-13', first))             # 非 datetime

    def test_apply_deal_semantics(self):
        from datetime import timezone
        from rental.deals import apply_deal, deal_state, DEAL
        tpe = timezone(timedelta(hours=8))
        first = datetime(2026, 1, 10, tzinfo=tpe)
        row = {'deal_status': 0, 'first_seen_at': first, 'deal_source': None, 'n_day_deal': None, 'deal_time': None}
        apply_deal(row, {'deal_time': datetime(2026, 1, 12, tzinfo=tpe), 'n_day_deal': 5})
        self.assertEqual(deal_state(row), {'deal_status': DEAL, 'deal_time': datetime(2026, 1, 12, tzinfo=tpe),
                                           'n_day_deal': 5, 'deal_source': 'deals'})
        row = {'deal_status': 0, 'first_seen_at': first}
        apply_deal(row, {'deal_time': datetime(2026, 1, 12, tzinfo=tpe), 'n_day_deal': None})
        self.assertEqual((row['deal_source'], row['n_day_deal']), ('deals', 2))
        row = {'deal_status': DEAL, 'deal_time': datetime(2026, 1, 14, tzinfo=tpe), 'first_seen_at': first,
               'deal_source': None, 'n_day_deal': None}
        apply_deal(row, None)
        self.assertEqual((row['deal_source'], row['n_day_deal']), ('inferred', 4))
        row = {'deal_status': DEAL, 'deal_time': datetime(2026, 1, 14, tzinfo=tpe), 'first_seen_at': first,
               'deal_source': 'deals', 'n_day_deal': 9}
        apply_deal(row, None)
        self.assertEqual((row['deal_source'], row['n_day_deal']), ('deals', 9))
        row = {'deal_status': 1, 'deal_source': None, 'n_day_deal': None}
        apply_deal(row, None)
        self.assertEqual(deal_state(row), {'deal_status': 1, 'deal_time': None, 'n_day_deal': None, 'deal_source': None})

    def test_fold_recovers_closed_house_for_late_deal_event(self):
        from rental.snapshot import fold, DEAL, NOT_FOUND
        stub = lambda hid, at: {'vendor_house_id': hid, 'seen_at': at, 'fingerprint': 'f', 'monthly_price': 9000}  # noqa: E731
        d1 = fold([], [stub('g', 'T1')], [{'vendor_house_id': 'g', 'crawled_at': 'T1d', 'deal_status': 0,
                                           'monthly_price': 9000, 'floor_ping': 8.0}], [], '2026-01-15')
        d2 = fold(d1, [], [{'vendor_house_id': 'g', 'crawled_at': 'T2d', 'deal_status': NOT_FOUND}], [], '2026-01-16')
        self.assertEqual((d2[0]['deal_status'], d2[0]['monthly_price']), (NOT_FOUND, 9000))
        d3 = fold(d2, [], [], [], '2026-01-17')
        self.assertEqual(d3, [])
        event = [{'vendor_house_id': 'g', 'seen_at': 'T4', 'deal_time': 'D', 'n_day_deal': 3}]
        blank = fold(d3, [], [], event, '2026-01-18')[0]
        self.assertEqual((blank['deal_status'], blank['deal_source'], blank['monthly_price'], blank['first_seen_at']),
                         (DEAL, 'deals', None, None))
        got = fold(d3, [], [], event, '2026-01-18', closed_rows={'g': d2[0]})[0]
        self.assertEqual((got['deal_status'], got['deal_source'], got['n_day_deal'], got['monthly_price'],
                          got['floor_ping'], got['first_seen_at'], got['source'], got['days_absent']),
                         (DEAL, 'deals', 3, 9000, 8.0, 'T1', 'carry', 3))
        self.assertEqual(fold(d3, [], [], [], '2026-01-18', closed_rows={'g': d2[0]}), [])


class LatestTableTests(unittest.TestCase):
    '''S3c 全戶最新狀態總表：latest(D) = fold(latest(D−1), final snapshot(D))，純函數。'''

    def _row(self, hid, date_str, **kw):
        from rental import contracts
        row = {name: None for name, _ in contracts.SNAPSHOT_FIELDS}
        row.update({'vendor': '591', 'vendor_house_id': hid, 'date': date_str, 'deal_status': 0,
                    'vendor_extra': '{"big": true}'})
        row.update(kw)
        return row

    def test_fold_overlays_present_houses_and_keeps_dropped_ones(self):
        from rental import latest
        d1 = latest.fold([], [self._row('a', '2026-09-10', monthly_price=10000),
                              self._row('b', '2026-09-10', monthly_price=20000)])
        self.assertEqual([r['vendor_house_id'] for r in d1], ['a', 'b'])
        self.assertNotIn('vendor_extra', d1[0])
        self.assertEqual(set(d1[0]), {n for n, _ in latest.LATEST_FIELDS})
        d2 = latest.fold(d1, [self._row('a', '2026-09-11', monthly_price=11000, days_absent=0),
                              self._row('c', '2026-09-11', monthly_price=30000)])
        by = {r['vendor_house_id']: r for r in d2}
        self.assertEqual(sorted(by), ['a', 'b', 'c'])
        self.assertEqual((by['a']['monthly_price'], by['a']['date']), (11000, '2026-09-11'))
        self.assertEqual((by['b']['monthly_price'], by['b']['date']), (20000, '2026-09-10'))  # 總表接住
        self.assertEqual(by['c']['date'], '2026-09-11')
        self.assertEqual(d1[1]['date'], '2026-09-10')                                        # 輸入不被改動

    def test_delta_is_snapshot_without_vendor_extra(self):
        from rental import latest
        rows = latest.delta([self._row('b', '2026-09-12'), self._row('a', '2026-09-12')])
        self.assertEqual([r['vendor_house_id'] for r in rows], ['a', 'b'])
        self.assertTrue(all('vendor_extra' not in r for r in rows))


class SnapshotFoldCommandTests(TempEnvTestCase):
    '''twrhctl snapshotfold／latestfold：昨日 final、今日 provisional、重放、總表接住回列戶。'''

    def setUp(self):
        super().setUp()
        from rental import tz
        self.tz = tz
        self.day = date.fromisoformat(TEST_DATE)
        self.yesterday = self.day - timedelta(days=1)

    def at(self, day, hour):
        return self.tz.make_aware(datetime(day.year, day.month, day.day, hour))

    def write_yesterday(self):
        '''昨日 snapshot：h1 昨日 detail（在 list）、h2 只在 list、h3 DEAL（三天沒在 list）。'''
        from rental import artifacts, snapshot
        y = self.yesterday
        first = self.at(y - timedelta(days=9), 3)
        rows = [
            snapshot_row('h1', y.isoformat(), source='detail', deal_status=0, monthly_price=10000,
                         floor_ping=20.0, last_detail_at=self.at(y, 3), last_fingerprint='fp1',
                         fingerprint_at_last_detail='fp1', last_seen_at=self.at(y, 2),
                         first_seen_at=first, days_absent=0),
            snapshot_row('h2', y.isoformat(), source='list', deal_status=0, monthly_price=7500,
                         last_detail_at=self.at(y - timedelta(days=5), 3), last_fingerprint='fp2',
                         last_seen_at=self.at(y, 2), first_seen_at=first, days_absent=0),
            snapshot_row('h3', y.isoformat(), source='carry', deal_status=snapshot.DEAL,
                         deal_time=self.at(y, 0), n_day_deal=4, deal_source='deals',
                         first_seen_at=first, days_absent=3),
        ]
        artifacts.write_snapshot(rows, '591', y.isoformat())
        return {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', y.isoformat())}

    def fold(self, *args):
        return check_command(self, 'snapshotfold', '--no-upload', *args)

    def test_folds_today_over_yesterday_and_is_idempotent(self):
        from rental import artifacts, contracts, snapshot
        prev = self.write_yesterday()
        t_list, t_detail, t_deal = self.at(self.day, 2), self.at(self.day, 3), self.at(self.day, 6)
        write_shard('list', [{'vendor_house_id': 'h1', 'seen_at': t_list.isoformat(),
                              'fingerprint': 'newfp', 'monthly_price': 12000}])
        write_shard('parsed', [{'vendor_house_id': 'h2', 'crawled_at': t_detail.isoformat(),
                                'deal_status': 0, 'monthly_price': 8000, 'floor_ping': 9.5}])
        write_shard('deals', [{'vendor_house_id': 'h1', 'seen_at': t_deal.isoformat(),
                               'deal_time': self.at(self.day, 0).isoformat(), 'n_day_deal': 2}])
        for tree in ('list', 'parsed', 'deals'):
            pack(self, tree)

        out = self.fold('--date', TEST_DATE)
        self.assertIn('keep as is', out)                             # 前日缺、昨日在：不動昨日
        today = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual(sorted(today), ['h1', 'h2'])                # h3 已關閉且無訊號：不攜帶
        h1, h2 = today['h1'], today['h2']
        self.assertEqual((h1['source'], h1['monthly_price'], h1['floor_ping'], h1['last_fingerprint'],
                          h1['fingerprint_at_last_detail'], h1['last_seen_at'], h1['days_absent']),
                         ('list', 12000, 20.0, 'newfp', 'fp1', t_list, 0))
        self.assertEqual((h1['deal_status'], h1['deal_time'], h1['n_day_deal'], h1['deal_source']),
                         (snapshot.DEAL, self.at(self.day, 0), 2, 'deals'))
        self.assertEqual((h2['source'], h2['monthly_price'], h2['floor_ping'], h2['last_detail_at'],
                          h2['fingerprint_at_last_detail'], h2['days_absent'], h2['first_seen_at']),
                         ('detail', 8000, 9.5, t_detail, 'fp2', 1, prev['h2']['first_seen_at']))
        self.assertEqual(h1['date'], TEST_DATE)
        self.assertEqual(set(h1), {name for name, _ in contracts.SNAPSHOT_FIELDS})

        self.fold('--date', TEST_DATE)                               # 同日重跑：結果相同
        again = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual(again, today)

    def test_db_era_modes_are_refused(self):
        for args in (('--bootstrap', '--date', TEST_DATE),
                     ('--backfill', '--from', '2026-01-10', '--to', '2026-01-11')):
            code, _out, err = run_command('snapshotfold', '--no-upload', *args)
            self.assertEqual(code, 1, args)
            self.assertIn('DB', err)
        self.assertEqual(run_command('snapshotfold', '--date', 'bad')[0], 1)

    def test_only_splits_final_and_provisional(self):
        '''S1（2026-09-19）：flow 把兩件事拆成 snapshotfinal（seed 前）與 snapshot 兩個 stage。'''
        from rental import artifacts
        y_str = self.yesterday.isoformat()
        base = (self.day - timedelta(days=3)).isoformat()
        artifacts.write_snapshot([snapshot_row('h1', base, source='detail', deal_status=0,
                                               monthly_price=9000)], '591', base)
        write_shard('parsed', [{'vendor_house_id': 'h2', 'crawled_at': self.at(self.day, 3).isoformat(),
                                'deal_status': 0, 'monthly_price': 8000, 'floor_ping': 9.5}])
        pack(self, 'parsed')

        # 昨日還沒摺就只摺今日＝順序錯：大聲失敗，不能悄悄用不存在的昨日
        code, _out, err = run_command('snapshotfold', '--no-upload', '--date', TEST_DATE,
                                      '--only', 'provisional')
        self.assertEqual(code, 1)
        self.assertIn('snapshotfinal', err)
        self.assertFalse(artifacts.snapshot_exists('591', y_str, None))
        self.assertFalse(artifacts.snapshot_exists('591', TEST_DATE, None))

        # --only final：前兩日都缺 → 從最近一份（3 天前）逐日重放到昨日，今日不碰
        out = self.fold('--date', TEST_DATE, '--only', 'final')
        self.assertIn('replay from {}'.format(base), out)
        self.assertEqual([r['vendor_house_id'] for r in artifacts.read_snapshot('591', y_str)], ['h1'])
        self.assertFalse(artifacts.snapshot_exists('591', TEST_DATE, None))

        before = artifacts.read_snapshot('591', y_str)
        self.fold('--date', TEST_DATE, '--only', 'provisional')
        today = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual(sorted(today), ['h1', 'h2'])
        self.assertEqual((today['h2']['monthly_price'], today['h1']['days_absent']), (8000, 3))
        self.assertEqual(artifacts.read_snapshot('591', y_str), before)

    def test_final_cold_starts_without_any_snapshot(self):
        from rental import artifacts
        write_shard('list', [{'vendor_house_id': 'n1', 'seen_at': self.at(self.yesterday, 2).isoformat(),
                              'fingerprint': 'f'}], date_str=self.yesterday.isoformat())
        pack(self, 'list', self.yesterday.isoformat())
        out = self.fold('--date', TEST_DATE, '--only', 'final')
        self.assertIn('cold start', out)
        rows = artifacts.read_snapshot('591', self.yesterday.isoformat())
        self.assertEqual([(r['vendor_house_id'], r['source']) for r in rows], [('n1', 'list')])

    def test_replays_from_last_snapshot_when_two_nights_missing(self):
        from rental import artifacts
        from tests.helpers import write_stubs
        artifacts.write_snapshot([snapshot_row('h1', '2026-01-12', deal_status=0, source='detail',
                                               monthly_price=9000)], '591', '2026-01-12')
        write_stubs(self, ['h1', 'h2'], date_str='2026-01-13')
        write_stubs(self, ['h1'], date_str='2026-01-14')
        self.fold('--date', TEST_DATE, '--only', 'final')
        self.assertTrue(artifacts.snapshot_exists('591', '2026-01-13'))
        by = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', '2026-01-14')}
        self.assertEqual(sorted(by), ['h1', 'h2'])
        self.assertEqual((by['h1']['monthly_price'], by['h2']['days_absent']), (10000, 1))

    def test_latestfold_folds_yesterday_and_snapshotfold_recovers_from_it(self):
        '''S3c：latestfold 把昨日 final 摺進總表（前日缺＝重放）；隔天 snapshotfold 對
        「昨日 snapshot 沒有、今日又回列」的戶從總表拿最後已知列。'''
        from rental import artifacts
        self.write_yesterday()
        self.fold('--date', TEST_DATE)                                  # 今日 provisional（h3 掉出）
        y_str = self.yesterday.isoformat()
        tomorrow = (self.day + timedelta(days=1)).isoformat()
        with mock.patch.dict(os.environ, {'TWRH_LATEST_BOOTSTRAP_FROM': y_str}):
            out = check_command(self, 'latestfold', '--date', TEST_DATE, '--no-upload')
        self.assertIn('bootstrap by replaying', out)
        table = {r['vendor_house_id']: r for r in artifacts.read_latest('591', y_str)}
        self.assertEqual(sorted(table), ['h1', 'h2', 'h3'])
        self.assertNotIn('vendor_extra', table['h1'])
        check_command(self, 'latestfold', '--date', tomorrow, '--no-upload')
        table2 = {r['vendor_house_id']: r for r in artifacts.read_latest('591', TEST_DATE)}
        self.assertEqual(sorted(table2), ['h1', 'h2', 'h3'])            # h3 掉出 snapshot、總表接住
        self.assertEqual((table2['h3']['date'], table2['h1']['date']), (y_str, TEST_DATE))
        # 明日：h3（DEAL、不在今日 snapshot）回列 → snapshotfold 從總表(今日) 拿回它的列
        write_shard('list', [{'vendor_house_id': 'h3',
                              'seen_at': self.at(self.day + timedelta(days=1), 2).isoformat(),
                              'fingerprint': 'fp3', 'monthly_price': 9000}], date_str=tomorrow)
        pack(self, 'list', tomorrow)
        out = self.fold('--date', tomorrow, '--only', 'provisional')
        self.assertIn('recovered from latest: 1', out)
        by = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', tomorrow)}
        self.assertEqual((by['h3']['deal_status'], by['h3']['monthly_price'], by['h3']['source']), (0, 9000, 'list'))
        self.assertEqual(by['h3']['first_seen_at'], table2['h3']['first_seen_at'])
        # 顯式重放與參數檢查
        check_command(self, 'latestfold', '--bootstrap', '--from', y_str, '--to', TEST_DATE, '--no-upload')
        self.assertEqual(len(artifacts.read_latest('591', TEST_DATE)), 3)
        self.assertEqual(run_command('latestfold', '--bootstrap', '--from', TEST_DATE, '--to', y_str)[0], 1)

    def test_recovers_late_deal_from_earlier_snapshot_without_latest(self):
        '''今日 deals 事件的戶不在昨日 snapshot、但在前幾天的 snapshot 有 → 補值（總表不在時的退路）。'''
        from rental import artifacts, snapshot
        y = self.yesterday
        before2 = y - timedelta(days=2)
        gone = snapshot_row('gone', before2.isoformat(), monthly_price=6500, floor_ping=9.0,
                            source='detail', deal_status=snapshot.NOT_FOUND,
                            first_seen_at=self.at(before2 - timedelta(days=10), 1),
                            last_seen_at=self.at(before2, 1), days_absent=0)
        artifacts.write_snapshot([gone], '591', before2.isoformat())
        artifacts.write_snapshot([snapshot_row('other', y.isoformat())], '591', y.isoformat())
        write_shard('deals', [{'vendor_house_id': 'gone', 'seen_at': self.at(self.day, 6).isoformat(),
                               'deal_time': self.at(y, 0).isoformat(), 'n_day_deal': 12,
                               'event_version': 1}])
        pack(self, 'deals')
        with mock.patch.dict(os.environ, {'TWRH_DEAL_LOOKBACK_DAYS': '7'}):
            self.fold('--date', TEST_DATE)
        today = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual((today['gone']['deal_status'], today['gone']['deal_source'], today['gone']['n_day_deal'],
                          today['gone']['monthly_price'], today['gone']['floor_ping'], today['gone']['days_absent']),
                         (snapshot.DEAL, 'deals', 12, 6500, 9.0, 3))
        self.assertEqual(today['gone']['first_seen_at'], gone['first_seen_at'])
        with mock.patch.dict(os.environ, {'TWRH_DEAL_LOOKBACK_DAYS': '1'}):
            self.fold('--date', TEST_DATE)
        today = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual((today['gone']['deal_status'], today['gone']['monthly_price']), (snapshot.DEAL, None))


if __name__ == '__main__':
    unittest.main()
