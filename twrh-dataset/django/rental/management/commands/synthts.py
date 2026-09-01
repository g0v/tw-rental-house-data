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
from datetime import timedelta

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


class Command(BaseCommand):
    help = 'Fill skipped OPENED houses\' daily HouseTS from House (diff mode)'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh-hours', type=int, default=12,
            help='detail_crawled_at 在 N 小時內視為本輪已爬、不合成（預設 12，'
                 '與 detail591 diff 種子的同輪窗口一致）')

    def handle(self, *_args, **options):
        ts = {
            'year': models.current_year(),
            'month': models.current_month(),
            'day': models.current_day(),
            'hour': models.current_stepped_hour(),
        }
        fresh_cutoff = timezone.now() - timedelta(hours=options['fresh_hours'])

        # 本輪爬過 detail 的物件快照已完整，不需要合成
        targets = House.objects.filter(
            deal_status=DealStatusType.OPENED,
        ).exclude(detail_crawled_at__gte=fresh_cutoff)

        copy_fields = [
            f.name for f in House._meta.get_fields()
            if getattr(f, 'concrete', False) and f.name not in SKIP_FIELDS
            and any(tf.name == f.name for tf in HouseTS._meta.get_fields()
                    if getattr(tf, 'concrete', False))
        ]

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
