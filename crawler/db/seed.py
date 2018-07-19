from .models import Vendor, SubRegion
from .enums import SubRegionField


def create_seed():
    Vendor.get_or_create(
        name='591 租屋網',
        site_url='https://rent.591.com.tw'
    )

    Vendor.get_or_create(
        name='好房網',
        site_url='https://rent.housefun.com.tw'
    )

    Vendor.get_or_create(
        name='蟹居網',
        site_url='https://rent.tmm.org.tw'
    )

    sub_region = SubRegionField()
    for name in sub_region.enum_to_int:
        row, created = SubRegion.get_or_create(
            id=sub_region.enum_to_int[name],
        )
        if not created:
            row.name = name.replace('台', '臺')
            row.save()


if __name__ == '__main__':
    create_seed()
