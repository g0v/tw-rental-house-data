import uuid
from django.db import models
from rental.models import JSONField
from .enums import RequestType
from rental.models import BaseTimeSeries, Vendor

# Create your models here.

class RequestTS(BaseTimeSeries):
    request_type = models.IntegerField(
        choices = [(tag, tag.value) for tag in RequestType]
    )
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    seed = JSONField()
    is_pending = models.BooleanField(default=False)
    last_status = models.IntegerField(null=True)
    owner = models.CharField(null=True, max_length=63)

    class Meta:
        db_table='request_ts'
        indexes = [
            models.Index(fields=['year', 'month', 'day', 'hour'])
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

    class Meta:
        unique_together = (
            ('year', 'month', 'day', 'hour', 'vendor'),
        )
