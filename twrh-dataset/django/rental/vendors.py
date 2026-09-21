'''vendor 登錄（S5 前置：Vendor 表是 house 三表停寫後 DB 最後一個讀取點）。

Vendor 表只有 id／name 兩個有人讀的欄，三列、自 2018 年沒變過，而且 id 是公開資料集
「租屋平台」欄背後的整數（只增不改，同 enums 的約定）。把它當常數放這裡，DB 拆掉之後
pipeline／queue／fold／manifest／export 才起得來。內容必須與 `fixtures/vendors.json` 一致
（矩陣有一例在對）；新增 vendor＝兩邊各加一列，id 往後編。

`get()`／`all()` 在還需要 ORM 的時候（house DB 回退、queue 還在 DB 記帳）回真的 Vendor
instance——那些路徑拿它當 FK 過濾條件，常數頂替不了；其餘時候回 `VendorRef`（id／pk／name），
完全不碰 DB。
'''
import os
from collections import namedtuple

from rental import filequeue
from rental.switches import house_db


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


def needs_orm():
    '''還有沒有哪條路徑要拿 Vendor 當 ORM 物件：house 三表回退中、或 queue 還在 DB 記帳。'''
    return house_db() or filequeue.db_bookkeeping()


def all(orm=None):   # noqa: A001 — 刻意對齊 Vendor.objects.all() 的讀法
    if needs_orm() if orm is None else orm:
        from rental.models import Vendor
        return list(Vendor.objects.all())
    return list(REGISTRY)


def get(name, orm=None):
    '''name 完全相符；找不到一律丟 LookupError（ORM 路徑的 DoesNotExist 在這裡轉成同一種）。'''
    if needs_orm() if orm is None else orm:
        from rental.models import Vendor
        try:
            return Vendor.objects.get(name=name)
        except Vendor.DoesNotExist:
            raise LookupError('Vendor "{}" is not defined.'.format(name))
    for ref in REGISTRY:
        if ref.name == name:
            return ref
    raise LookupError('Vendor "{}" is not defined.'.format(name))


def by_short(short, orm=None):
    '''目錄短名（'591'）→ vendor；找不到回 None。'''
    from rental.raws import vendor_dirname
    for vendor in all(orm):
        if vendor_dirname(vendor.name) == short:
            return vendor
    return None
