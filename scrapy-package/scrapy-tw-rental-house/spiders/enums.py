from enum import IntEnum
from os import path
import json


class DealStatusType(IntEnum):
    OPENED = 0
    NOT_FOUND = 1
    DEAL = 2

UNKNOWN_ENUM = 0xffff

BuildingType = IntEnum('BuildingType', [
    ('公寓', 0),
    ('透天', 1),
    ('電梯大樓', 2),
    ('華廈', 3),
    ('辦公商業大樓', 4),
    ('倉庫', 5),
    ('店面（店鋪）', 6),
    ('廠辦', 7),
    ('工廠', 8),
    ('農舍', 9)
])

class PropertyType(IntEnum):
    整層住家 = 0
    獨立套房 = 1
    分租套房 = 2
    雅房 = 3
    車位 = 4
    其他 = 5
    倉庫 = 6
    場地 = 7
    攤位 = 8


class ContactType(IntEnum):
    屋主 = 0
    代理人 = 1
    房仲 = 2


class DepositType(IntEnum):
    月 = 0
    定額 = 1
    面議 = 2
    其他 = 3


class GenderType(IntEnum):
    不限 = 0
    女 = 1
    男 = 2
    其他 = 3


tw_regions_path = '{}/tw_regions.json'.format(
    path.dirname(path.realpath(__file__)))

with open(tw_regions_path) as regions_file:
    tw_regions = json.load(regions_file)

TopRegionType = IntEnum('TopRegionType', tw_regions['top_region'])

SubRegionType = IntEnum('SubRegionType', tw_regions['sub_region'])
