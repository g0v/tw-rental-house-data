"""L-C(8)：diff 模式下補齊被 skip 物件的當日 HouseTS——合成快照。

diff 模式（detail591 -a seed_mode=diff）只對種子四類爬 detail，被 skip
的 OPENED 物件當日 HouseTS 只有 list 層欄位（或缺席一天者整列缺席）。
本指令在 detail 迴圈後、syncstateful 前執行，把 House 現值（＝上次
detail 的值）填進當日 HouseTS 的空欄位，維持「每個 open 物件每日一列」
的資料密度；有補值的列標 is_synthesized=True，供資料使用者與月度 gate
分辨爬取值／合成值。detail 欄位最舊 refresh_days-1 天（見 dx-roadmap
L-C-8，發布語意需操作者拍板後才在 production 啟用 diff 模式）。

full 模式（現行預設）下毋需執行；重複執行冪等（只填 NULL 欄位）。
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from rental import models
from rental.enums import DealStatusType
from rental.models import House, HouseTS

# 逐欄複製時跳過的欄位：key／bucket／bookkeeping，以及 list 戳記
SKIP_FIELDS = {
    'id', 'vendor', 'vendor_house_id', 'created', 'updated',
    'year', 'month', 'day', 'hour', 'is_synthesized', 'list_crawled_at',
}


def bucket_window(ts):
    '''這一列的日期桶 [start, end)（本地時區）。hour 目前恆 0、步長 24
    （current_stepped_hour），所以桶＝當地一整天。'''
    start = timezone.make_aware(
        datetime(ts['year'], ts['month'], ts['day'], ts['hour']),
        timezone.get_current_timezone())
    return start, start + timedelta(hours=24)


class Command(BaseCommand):
    help = 'Fill skipped OPENED houses\' daily HouseTS from House (diff mode)'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            '--closed-only', action='store_true',
            help='只跑關閉／成交列補齊（回補過去日期用：第一段會對 OPENED 戶建當日列，'
                 '對過去日期會生出當時不存在的戶）')
        parser.add_argument(
            '--no-create', action='store_true',
            help='只補既有列、不建列（回補過去日期用：當時不在架的戶不該被生出來）。'
                 '搭配 --date／TWRH_TARGET_DATE 回補歷史的稀疏列')

    def handle(self, *_args, **options):
        ts = {
            'year': models.current_year(),
            'month': models.current_month(),
            'day': models.current_day(),
            'hour': models.current_stepped_hour(),
        }
        bucket_start, bucket_end = bucket_window(ts)

        if options['closed_only']:
            self.fill_closed(ts)
            return

        # 「本輪爬過 detail 的物件快照已完整」＝detail 落在**本列的日期桶內**。
        # 原本用滾動 12 小時判斷，在一天一跑時等價；前緣掃描（每 3 小時）之後
        # 就錯了：傍晚 sweep（17:01／20:01／23:01）抓到的戶，detail 寫進的是
        # 「昨天」那列，隔天 04:2x synthts 跑時它才 8–12 小時大，被當成本輪已爬
        # 排除掉——今天這列於是永遠停在 list-only 稀疏列（2026-09-16 實測 4,737 列，
        # 佔當日座標空值的九成；House 現值都在，只是沒填進當日列）。
        targets = House.objects.filter(
            deal_status=DealStatusType.OPENED,
        ).exclude(
            detail_crawled_at__gte=bucket_start,
            detail_crawled_at__lt=bucket_end,
        )

        copy_fields = [
            f.name for f in House._meta.get_fields()
            if getattr(f, 'concrete', False) and f.name not in SKIP_FIELDS
            and any(tf.name == f.name for tf in HouseTS._meta.get_fields()
                    if getattr(tf, 'concrete', False))
        ]

        if options['no_create']:
            self.fill_existing_opened(ts, bucket_start, bucket_end, copy_fields)
            self.fill_closed(ts)
            return

        n_created = n_filled = n_untouched = 0
        for house in targets.iterator(chunk_size=1000):
            house_ts, created = HouseTS.objects.get_or_create(
                **ts,
                vendor=house.vendor,
                vendor_house_id=house.vendor_house_id,
            )
            filled = []
            for name in copy_fields:
                if getattr(house_ts, name) is None \
                        and getattr(house, name) is not None:
                    setattr(house_ts, name, getattr(house, name))
                    filled.append(name)
            if filled:
                house_ts.is_synthesized = True
                house_ts.save(update_fields=filled + ['is_synthesized', 'updated'])
                n_filled += 1
            else:
                n_untouched += 1
            if created:
                n_created += 1

        print('{}/{}/{}: synthts filled {} (rows created {}, untouched {})'.format(
            ts['year'], ts['month'], ts['day'], n_filled, n_created, n_untouched))
        self.fill_closed(ts)

    def fill_existing_opened(self, ts, bucket_start, bucket_end, copy_fields):
        '''回補過去日期用：走「那天存在的 OPENED 列」再回查 House，而不是走
        「現在 OPENED 的 House」。差別在周轉——9/8 開著、如今已關的戶不在
        House(OPENED) 裡，而它那天那列又是 OPENED、fill_closed 也不收，
        兩邊都撈不到。House 現值仍保有最後一次 detail 的值，補得進去。
        只補既有列、不建列（當時不在架的戶不該被生出來）。'''
        rows = list(HouseTS.objects.filter(
            **ts, deal_status=DealStatusType.OPENED))
        n_filled = n_untouched = n_no_house = n_fresh = 0
        for i in range(0, len(rows), 1000):
            chunk = rows[i:i + 1000]
            houses = {(h.vendor_id, h.vendor_house_id): h for h in House.objects.filter(
                vendor__in={r.vendor_id for r in chunk},
                vendor_house_id__in=[r.vendor_house_id for r in chunk])}
            for house_ts in chunk:
                house = houses.get((house_ts.vendor_id, house_ts.vendor_house_id))
                if house is None:
                    n_no_house += 1
                    continue
                # 那天就爬過 detail 的列＝爬取值，不覆蓋（同日跑的判準）
                if house.detail_crawled_at is not None \
                        and bucket_start <= house.detail_crawled_at < bucket_end:
                    n_fresh += 1
                    continue
                filled = [name for name in copy_fields
                          if getattr(house_ts, name) is None
                          and getattr(house, name) is not None]
                if not filled:
                    n_untouched += 1
                    continue
                for name in filled:
                    setattr(house_ts, name, getattr(house, name))
                house_ts.is_synthesized = True
                house_ts.save(update_fields=filled + ['is_synthesized', 'updated'])
                n_filled += 1
        print('{}/{}/{}: synthts --no-create filled {} of {} opened rows '
              '(untouched {}, detail-in-bucket {}, no house {})'.format(
                  ts['year'], ts['month'], ts['day'], n_filled, len(rows),
                  n_untouched, n_fresh, n_no_house))

    def fill_closed(self, ts):
        copy_fields = [
            f.name for f in House._meta.get_fields()
            if getattr(f, 'concrete', False) and f.name not in SKIP_FIELDS
            and any(tf.name == f.name for tf in HouseTS._meta.get_fields()
                    if getattr(tf, 'concrete', False))
        ]
        # 關閉／成交列（2026-09-12 拍板）：pipeline 對 404 只寫 deal_status、deal591 只寫
        # 三個事件欄，當日列其餘全 NULL——公開 CSV 成交當天那列沒租金沒座標。這裡把
        # House 現值（最後一次 detail）補進去，與 snapshot「關閉當天保留最後已知狀態」
        # 同形（S3 export 兩路比對的前提）。只補既有列、不建列；狀態三欄不動
        # （Issue #9 sticky：House 可能已回滾成 DEAL 而該列是 NOT_FOUND）。
        state_fields = {'deal_status', 'deal_time', 'n_day_deal'}
        closed_fields = [name for name in copy_fields if name not in state_fields]
        n_closed_filled = 0
        closed_rows = list(HouseTS.objects.filter(**ts).exclude(
            deal_status=DealStatusType.OPENED))
        for i in range(0, len(closed_rows), 1000):
            chunk = closed_rows[i:i + 1000]
            houses = {(h.vendor_id, h.vendor_house_id): h for h in House.objects.filter(
                vendor__in={r.vendor_id for r in chunk},
                vendor_house_id__in=[r.vendor_house_id for r in chunk])}
            for house_ts in chunk:
                house = houses.get((house_ts.vendor_id, house_ts.vendor_house_id))
                if house is None:
                    continue
                filled = [name for name in closed_fields
                          if getattr(house_ts, name) is None and getattr(house, name) is not None]
                if not filled:
                    continue
                for name in filled:
                    setattr(house_ts, name, getattr(house, name))
                house_ts.is_synthesized = True
                house_ts.save(update_fields=filled + ['is_synthesized', 'updated'])
                n_closed_filled += 1
        print('{}/{}/{}: synthts filled {} closed/dealt rows from House'.format(
            ts['year'], ts['month'], ts['day'], n_closed_filled))
