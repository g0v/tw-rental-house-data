from django.db import models
from django.db.models import JSONField, Q
from rental.models import BaseTimeSeries, Vendor
from .enums import RequestType, RequestStatus, REQUEST_STATUS_ACTIVE

# Create your models here.

class RequestTS(BaseTimeSeries):
    request_type = models.IntegerField(
        choices = [(tag, tag.value) for tag in RequestType]
    )
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    seed = JSONField()
    # 1-1 前的認領旗標，已由 status=IN_FLIGHT 取代；欄位暫留一版避免
    # 部署時新舊 code 併存踩空欄，之後的 migration 再移除
    is_pending = models.BooleanField(default=False)
    last_status = models.IntegerField(null=True)
    owner = models.CharField(null=True, max_length=63)
    # --- 1-1 顯式狀態機（architecture-roadmap 軸 A）---
    # 「刪列＝完成」廢除：errback／parse error 必寫終結狀態，
    # 收工斷言 seeds == terminals（queuefinalize）。列的清理從正確性
    # 條件降級為清理政策（滾動窗口，queuefinalize --cleanup-days）
    status = models.IntegerField(
        choices = [(tag, tag.value) for tag in RequestStatus],
        default = RequestStatus.PENDING,
    )
    attempts = models.IntegerField(default=0)
    # 失敗分類（http_403／DNSLookupError／parse_error:*…），供 GROUP BY 統計
    error = models.CharField(null=True, max_length=255)

    class Meta:
        db_table='request_ts'
        indexes = [
            models.Index(fields=['year', 'month', 'day', 'hour']),
            # 認領熱路徑只掃未終結列：終結列自動掉出 index，
            # claim 掃描量與表總量無關（1-1 不刪列的效能對策）
            models.Index(
                fields=['year', 'month', 'day', 'hour',
                        'vendor', 'request_type', 'attempts'],
                name='request_ts_claim_idx',
                condition=Q(status__in=[int(s) for s in REQUEST_STATUS_ACTIVE]),
            ),
        ]

class Stats(BaseTimeSeries):
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    n_list_fail = models.IntegerField(default=0)
    n_expected = models.IntegerField(default=0)
    n_crawled = models.IntegerField(default=0)
    n_fail = models.IntegerField(default=0)
    n_new_item = models.IntegerField(default=0)
    n_closed = models.IntegerField(default=0)
    n_dealt = models.IntegerField(default=0)
    # 當日 OPENED 中有出現在 list 的數量（分母＝n_crawled - n_closed - n_dealt）。
    # list 完整度哨兵（L-B），比率持續偏低代表 list 掃描漏尾頁
    n_open_in_list = models.IntegerField(default=0)

    class Meta:
        unique_together = (
            ('year', 'month', 'day', 'hour', 'vendor'),
        )
