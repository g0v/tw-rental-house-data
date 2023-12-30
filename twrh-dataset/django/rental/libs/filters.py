from django.db.models import F
from rental import enums

big6 = {
    'top_region__in': [
        enums.TopRegionType.台北市,
        enums.TopRegionType.新北市,
        enums.TopRegionType.桃園市,
        enums.TopRegionType.台中市,
        enums.TopRegionType.台南市,
        enums.TopRegionType.高雄市,
    ]
}

should_be_house = {
    'building_type__in': [
        enums.BuildingType.公寓,
        enums.BuildingType.透天,
        enums.BuildingType.電梯大樓
    ],
    'property_type__in': [
        enums.PropertyType.整層住家,
        enums.PropertyType.獨立套房,
        enums.PropertyType.分租套房,
        enums.PropertyType.雅房
    ],
    'total_floor__lt': 90,
    'floor__lt': 90,
    'floor__lte': (F('total_floor')+2),
    'floor_ping__lt': 500,
    'per_ping_price__lte': 15000,
}
