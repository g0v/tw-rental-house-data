'''vendor 登錄：id／name 常數（S5 前置起取代 DB 的 Vendor 表；S6 起是唯一來源）。

id 是公開資料集「租屋平台」欄背後的整數（只增不改，同 enums 的約定）。新增 vendor＝加一列，
id 往後編；vendor 維度的其餘設定在 crawler/vendor_profiles.py。
'''
import os
from collections import namedtuple



class VendorRef(namedtuple('VendorRef', ['id', 'name'])):
    __slots__ = ()

    @property
    def pk(self):
        return self.id


REGISTRY = (
    VendorRef(1, '591 租屋網'),
    VendorRef(2, '好房網'),
    VendorRef(3, '蟹居網'),
)


def all():   # noqa: A001 — 刻意對齊舊 Vendor.objects.all() 的讀法
    return list(REGISTRY)


def get(name):
    '''name 完全相符；找不到丟 LookupError。'''
    for ref in REGISTRY:
        if ref.name == name:
            return ref
    raise LookupError('Vendor "{}" is not defined.'.format(name))


def by_short(short):
    '''目錄短名（'591'）→ vendor；找不到回 None。'''
    from rental.raws import vendor_dirname
    for vendor in REGISTRY:
        if vendor_dirname(vendor.name) == short:
            return vendor
    return None
