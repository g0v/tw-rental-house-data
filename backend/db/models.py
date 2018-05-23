from peewee import DateTimeField, IntegerField, BooleanField, AutoField, \
    FloatField, Model, Expression, CharField, ForeignKeyField, TextField
import datetime
import os
from . import enums
from backend.settings import ENVIRONMENT, DB

if ENVIRONMENT != 'development' and DB:
    from playhouse.postgres_ext import PostgresqlExtDatabase, JSONField
    db = PostgresqlExtDatabase(DB['NAME'], **DB['ARGS'])
else:
    from playhouse.sqlite_ext import SqliteExtDatabase, JSONField
    dbBase = os.path.dirname(os.path.realpath(__file__))
    dbName = '{}/../../debug.db'.format(dbBase)
    db = SqliteExtDatabase(dbName, pragmas=(
        ('journal_mode', 'wal'),   # Use WAL-mode (you should always use this!)
        ('foreign_keys', 1))   # Enforce foreign-key constraints.
    )


def mod(lhs, rhs):
    return Expression(lhs, '%', rhs)


tw_tz = datetime.timezone(datetime.timedelta(hours=8))


def current_year():
    return datetime.datetime.now(tz=tw_tz).year


def current_month():
    return datetime.datetime.now(tz=tw_tz).month


def current_day():
    return datetime.datetime.now(tz=tw_tz).day


def current_stepped_hour():
    current = datetime.datetime.now(tz=tw_tz)
    # Let's do it once for now
    return current.hour - current.hour % 24


def now_tuple():
    now = datetime.datetime.now(tz=tw_tz)
    # Let's do it once for now
    return [now.year, now.month, now.day, 0]
    # return [now.year, now.month, now.day, now.hour - now.hour % 12]


class BaseModel(Model):
    created = DateTimeField(default=datetime.datetime.now)
    updated = DateTimeField(default=datetime.datetime.now)

    class Meta:
        database = db


class Vendor(BaseModel):
    id = AutoField()
    name = CharField(unique=True)
    icon = CharField(null=True)
    site_url = CharField()


class SubRegion(BaseModel):
    id = IntegerField(primary_key=True)
    name = CharField(null=True)

    class Meta:
        indexes = (
            (('name', ), True),
        )
        table_name = 'sub_region'


class BaseHouse(BaseModel):
    top_region = enums.TopRegionField(null=True)
    sub_region = enums.SubRegionField(null=True)
    deal_time = DateTimeField(null=True)
    deal_status = enums.DealStatusField(default='OPENED')
    n_day_deal = IntegerField(null=True)
    vendor = ForeignKeyField(Vendor)
    vendor_house_id = CharField()
    vendor_house_url = CharField(null=True)
    # price related
    monthly_price = IntegerField(null=True)
    deposit_type = enums.DepositTypeField(null=True)
    n_month_deposit = FloatField(null=True)
    deposit = IntegerField(null=True)
    is_require_management_fee = BooleanField(null=True)
    monthly_management_fee = IntegerField(null=True)
    has_parking = BooleanField(null=True)
    is_require_parking_fee = BooleanField(null=True)
    monthly_parking_fee = IntegerField(null=True)
    per_ping_price = FloatField(null=True)
    # other basic info
    building_type = enums.BuildingTypeField(null=True)
    property_type = enums.PropertyTypeField(null=True)
    is_rooftop = BooleanField(null=True)
    floor = IntegerField(null=True)
    total_floor = IntegerField(null=True)
    dist_to_highest_floor = IntegerField(null=True)
    floor_ping = FloatField(null=True)
    n_living_room = IntegerField(null=True)
    n_bed_room = IntegerField(null=True)
    n_bath_room = IntegerField(null=True)
    n_balcony = IntegerField(null=True)
    apt_feature_code = CharField(null=True)
    rough_address = CharField(null=True)
    rough_gps = CharField(null=True)
    # boolean map
    # eletricity: true, water: true, gas: true, internet: true, cable_tv: true
    additional_fee = JSONField(null=True)
    # school, park, dept_store, conv_store, traditional_mkt, night_mkt,
    # hospital, police_office
    living_functions = JSONField(null=True)
    # subway, bus, public_bike, train, hsr
    transportation = JSONField(null=True)
    has_tenant_restriction = BooleanField(null=True)
    has_gender_restriction = BooleanField(null=True)
    gender_restriction = enums.GenderTypeField(null=True)
    can_cook = BooleanField(null=True)
    allow_pet = BooleanField(null=True)
    has_perperty_registration = BooleanField(null=True)
    # undermined for now
    facilities = JSONField(null=True)
    contact = enums.ContactTypeField(null=True)
    agent_org = CharField(null=True)
    imgs = JSONField(null=True)


class House(BaseHouse):
    id = AutoField()

    class Meta:
        indexes = (
            (('vendor', 'vendor_house_id'), True),
            (('updated', ), True)
        )


class HouseEtc(BaseModel):
    house = ForeignKeyField(House, primary_key=True)
    vendor = ForeignKeyField(Vendor)
    vendor_house_id = IntegerField()
    detail_dict = JSONField(null=True)
    list_raw = TextField(null=True)
    detail_raw = TextField(null=True)
    could_be_rooftop = BooleanField(null=True)

    class Meta:
        indexes = (
            (('vendor', 'vendor_house_id'), False),
        )
        table_name = 'house_etc'


class BaseTSModel(BaseModel):
    id = AutoField()
    year = IntegerField(default=current_year)
    month = IntegerField(default=current_month)
    day = IntegerField(default=current_day)
    hour = IntegerField(default=current_stepped_hour)


class RequestTS(BaseTSModel):
    request_type = enums.RequestTypeField()
    vendor = ForeignKeyField(Vendor)
    seed = JSONField()
    is_pending = BooleanField(default=False)
    last_status = IntegerField(null=True)

    class Meta:
        indexes = (
            (('year', 'month', 'day', 'hour'), False),
        )
        table_name = 'request_ts'


class RegionTS(BaseTSModel):
    top_region = CharField()
    sub_region = CharField()
    count = IntegerField(null=True)

    class Meta:
        indexes = (
            (('year', 'month', 'day', 'hour', 'top_region'), True),
        )
        table_name = 'region_ts'


class HouseTS(BaseTSModel, BaseHouse):
    class Meta:
        indexes = (
            (('year', 'month', 'day', 'hour', 'vendor', 'vendor_house_id'),
                True),
            (('created', 'deal_status'), False),
        )
        table_name = 'house_ts'


db.connect()
db.create_tables([
    RegionTS, HouseTS, RequestTS, House, HouseEtc, Vendor, SubRegion])
