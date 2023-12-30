import os
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
django.setup()

from rental.models import House, HouseTS, Vendor
from rental.enums import DealStatusType

vendor = Vendor.objects.get(pk=1)

basic_deal = 'basic_deal_4d'
basic_ts = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': basic_deal
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=basic_deal, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**basic_ts, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**basic_ts, day=2, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**basic_ts, day=3, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**basic_ts, day=4, deal_status=DealStatusType.DEAL)

id = 'douple_deal_2d'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=2, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=3, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=4, deal_status=DealStatusType.DEAL)


id = 'fast_deal_1d'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=4, deal_status=DealStatusType.DEAL)


id = 'cont_deal_3d'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=2, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=3, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=4, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=5, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=6, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=7, deal_status=DealStatusType.DEAL)


id = 'simple_deal_before_not_found_4d'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=2, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=3, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=4, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=5, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=6, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=7, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=8, deal_status=DealStatusType.NOT_FOUND)

id = 'deal_contain_not_found_6d'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=2, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=3, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=4, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=5, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=6, deal_status=DealStatusType.DEAL)


id = 'repeated_close'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=2, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=3, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=4, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=5, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=6, deal_status=DealStatusType.NOT_FOUND)


id = 'non_cont_opened'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=2, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=3, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=10, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=11, deal_status=DealStatusType.NOT_FOUND)



id = 'non_cont_opened_3d'
ts_param = {
    'year': 2018,
    'month': 8,
    'vendor': vendor,
    'vendor_house_id': id
}

House.objects.get_or_create(vendor=vendor, vendor_house_id=id, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=1, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=2, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=3, deal_status=DealStatusType.DEAL)
HouseTS.objects.get_or_create(**ts_param, day=10, deal_status=DealStatusType.OPENED)
HouseTS.objects.get_or_create(**ts_param, day=11, deal_status=DealStatusType.NOT_FOUND)
HouseTS.objects.get_or_create(**ts_param, day=12, deal_status=DealStatusType.DEAL)
