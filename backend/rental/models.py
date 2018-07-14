from django.db import models
from datetime import datetime, timezone, timedelta
from .enums import DealStatusType, BuildingType, PropertyType, ContactType, \
    DepositType, GenderType, TopRegionType, SubRegionType

from django.conf import settings

# Since django doesn't support general JSONField that utilize json type in all DB,
# It's better to let user to determine which column type s/he want
if hasattr(settings, 'USE_NATIVE_JSONFIELD') and settings.USE_NATIVE_JSONFIELD:
    from django.contrib.postgres.fields import JSONField as superJSONField
else:
    from jsonfield import JSONField as superJSONField

# 
class JSONField(superJSONField):
    pass


def current_year():
    tw_tz = timezone(timedelta(hours=8))
    return datetime.now(tz=tw_tz).year

def current_month():
    tw_tz = timezone(timedelta(hours=8))
    return datetime.now(tz=tw_tz).month

def current_day():
    tw_tz = timezone(timedelta(hours=8))
    return datetime.now(tz=tw_tz).day

def current_stepped_hour():
    tw_tz = timezone(timedelta(hours=8))
    current = datetime.now(tz=tw_tz)
    # Let's do only one step for now
    return current.hour - current.hour % 24


class BaseModel(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class BaseTimeSeries(BaseModel):
    year = models.IntegerField(default=current_year)
    month = models.IntegerField(default=current_month)
    day = models.IntegerField(default=current_day)
    hour = models.IntegerField(default=current_stepped_hour)
    
    class Meta:
        abstract = True

class Vendor(models.Model):
    name = models.CharField(unique=True, max_length=200)
    icon = models.CharField(null=True, max_length=200)
    site_url = models.URLField()

    class Meta:
        db_table='vendor'

class SubRegion(BaseModel):
    name = models.CharField(null=True, unique=True, max_length=64)

    class Meta:
        db_table = 'sub_region'

class BaseHouse(models.Model):
    top_region = models.IntegerField(
        choices = [(tag, tag.value) for tag in TopRegionType],
        null=True
    )
    sub_region = models.IntegerField(
        choices = [(tag, tag.value) for tag in SubRegionType],
        null=True
    )
    deal_time = models.DateTimeField(null=True)
    deal_status = models.IntegerField(
        choices = [(tag, tag.value) for tag in DealStatusType],
        default = DealStatusType.OPENED
    )
    n_day_deal = models.IntegerField(null=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    vendor_house_id = models.CharField(max_length=128)
    vendor_house_url = models.URLField(null=True)
    # price related
    monthly_price = models.IntegerField(null=True)
    deposit_type = models.IntegerField(
        choices = [(tag, tag.value) for tag in DepositType],
        null=True
    )
    n_month_deposit = models.FloatField(null=True)
    deposit = models.IntegerField(null=True)
    is_require_management_fee = models.NullBooleanField(null=True)
    monthly_management_fee = models.IntegerField(null=True)
    has_parking = models.NullBooleanField(null=True)
    is_require_parking_fee = models.NullBooleanField(null=True)
    monthly_parking_fee = models.IntegerField(null=True)
    per_ping_price = models.FloatField(null=True)
    # other basic info
    building_type = models.IntegerField(
        choices = [(tag, tag.value) for tag in BuildingType],
        null=True
    )
    property_type = models.IntegerField(
        choices = [(tag, tag.value) for tag in PropertyType],
        null=True
    )
    is_rooftop = models.NullBooleanField(null=True)
    floor = models.IntegerField(null=True)
    total_floor = models.IntegerField(null=True)
    dist_to_highest_floor = models.IntegerField(null=True)
    floor_ping = models.FloatField(null=True)
    n_living_room = models.IntegerField(null=True)
    n_bed_room = models.IntegerField(null=True)
    n_bath_room = models.IntegerField(null=True)
    n_balcony = models.IntegerField(null=True)
    apt_feature_code = models.CharField(null=True, max_length=16)
    rough_address = models.CharField(null=True, max_length=256)
    rough_gps = models.CharField(null=True, max_length=32)
    # boolean map
    # eletricity: true, water: true, gas: true, internet: true, cable_tv: true
    additional_fee = JSONField(null=True)
    # school, park, dept_store, conv_store, traditional_mkt, night_mkt,
    # hospital, police_office
    living_functions = JSONField(null=True)
    # subway, bus, public_bike, train, hsr
    transportation = JSONField(null=True)
    has_tenant_restriction = models.NullBooleanField(null=True)
    has_gender_restriction = models.NullBooleanField(null=True)
    gender_restriction = models.IntegerField(
        choices = [(tag, tag.value) for tag in GenderType],
        null=True
    )
    can_cook = models.NullBooleanField(null=True)
    allow_pet = models.NullBooleanField(null=True)
    has_perperty_registration = models.NullBooleanField(null=True)
    # undermined for now
    facilities = JSONField(null=True)
    contact = models.IntegerField(
        choices = [(tag, tag.value) for tag in ContactType],
        null=True
    )
    agent_org = models.CharField(null=True, max_length=256)
    imgs = JSONField(null=True)

    class Meta:
        abstract = True  

class House(BaseHouse, BaseModel):

    class Meta:
        db_table='house'
        indexes = [
            models.Index(fields=['updated'])
        ]
        unique_together = (
            ('vendor', 'vendor_house_id'),
        )

class HouseEtc(BaseModel):
    house = models.OneToOneField(
        House,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='etc')
    # TODO: remove vendor* after we have inital migration
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE)
    vendor_house_id = models.CharField(max_length=128)
    detail_dict = JSONField(null=True)
    list_raw = models.TextField(null=True)
    detail_raw = models.TextField(null=True)
    could_be_rooftop = models.NullBooleanField(null=True)

    class Meta:
        db_table = 'house_etc'
        unique_together = (
            ('vendor', 'vendor_house_id'),
        )

class RegionTS(BaseTimeSeries):
    top_region = models.CharField(max_length=16)
    sub_region = models.CharField(max_length=16)
    count = models.IntegerField(null=True)

    class Meta:
        db_table = 'region_ts'
        unique_together = (
            ('year', 'month', 'day', 'hour', 'top_region'),
        )

class HouseTS(BaseTimeSeries, BaseHouse):
    class Meta:
        db_table = 'house_ts'
        indexes = [
            models.Index(fields=['created', 'deal_status'])
        ]
        unique_together = (
            ('year', 'month', 'day', 'hour', 'vendor', 'vendor_house_id'),      
        )

