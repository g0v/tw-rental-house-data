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

    class Meta:
        db_table='request_ts'
        indexes = [
            models.Index(fields=['year', 'month', 'day', 'hour'])
        ]
