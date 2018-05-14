from peewee import IntegerField
import json
from os import path

class EnumList():
    enums = {}

    def __init__(self, enum_to_int):
        self.enums = enum_to_int

    def __getattr__(self, name):
        if name in self.enums:
            return name
        else:
            raise AttributeError(
                '{} undefined in this enum - {}'.format(name, self.enums))


class EnumField(IntegerField):

    UNKNOWN = 0xffff

    @classmethod
    def create_enums(cls):
        '''
        enums should be list of following format:
          1. list of string. Use index as enumaration key
          2. list of {'int': <int>, 'enum': <str>}, use 'int' as enum key

          When 2nd format is used, duplicated enum key is allowed.
          This can be used when we need alias of enum string
          Last enum with the same key will be the standard enum string
        '''
        enums = cls.enums
        cls.int_to_enum = {}
        cls.enum_to_int = {}
        for (index, item) in enumerate(enums):
            if type(item) is str:
                cls.int_to_enum[index] = item
                cls.enum_to_int[item] = index
            elif type(item) is dict:
                cls.int_to_enum[item['int']] = item['enum']
                cls.enum_to_int[item['enum']] = item['int']

        cls.int_to_enum[cls.UNKNOWN] = '__UNKNOWN__'
        cls.enum_to_int['__UNKNOWN__'] = cls.UNKNOWN
        cls.enums = EnumList(cls.enum_to_int)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @classmethod
    def db_value(cls, value):
        try:
            return cls.enum_to_int[value]
        except KeyError:
            return cls.UNKNOWN

    @classmethod
    def python_value(cls, value):
        try:
            return cls.int_to_enum[value]
        except KeyError:
            return '__UNKNOWN__'


class DealStatusField(EnumField):
    enums = [
        'OPENED',
        'NOT_FOUND',
        'DEAL'
    ]


class BuildingTypeField(EnumField):
    enums = [
        '公寓',
        '透天',
        '電梯大樓',
        '華廈',
        '辦公商業大樓',
        '倉庫',
        '店面（店鋪）',
        '廠辦'
    ]


class PropertyTypeField(EnumField):
    enums = [
        '整層住家',
        '獨立套房',
        '分租套房',
        '雅房',
        '車位',
        '其他',
        '倉庫',
        '場地'
    ]


class ContactTypeField(EnumField):
    enums = [
        '屋主',
        '代理人',
        '房仲'
    ]


class RequestTypeField(EnumField):
    enums = [
        'LIST',
        'DETAIL'
    ]


class DepositTypeField(EnumField):
    enums = [
        '月',
        '定額',
        '面議',
        '其他'
    ]


class GenderTypeField(EnumField):
    enums = [
        '不限',
        '女',
        '男',
        '其他'
    ]


tw_regions_path = '{}/tw_regions.json'.format(
    path.dirname(path.realpath(__file__)))

with open(tw_regions_path) as regions_file:
    tw_regions = json.load(regions_file)


class TopRegionField(EnumField):
    enums = tw_regions['top_region']


class SubRegionField(EnumField):
    enums = tw_regions['sub_region']


enum_list = [
    DealStatusField,
    BuildingTypeField,
    PropertyTypeField,
    ContactTypeField,
    RequestTypeField,
    DepositTypeField,
    GenderTypeField,
    TopRegionField,
    SubRegionField
]

for enum_type in enum_list:
    enum_type.create_enums()
