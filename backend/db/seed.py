from .models import Vendor


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


if __name__ == '__main__':
    create_seed()
