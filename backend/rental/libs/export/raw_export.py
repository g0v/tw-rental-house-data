from django.core.paginator import Paginator
from rental.libs import filters
from rental.models import House
from rental import enums
from .export import Export
from .field import Field

class RawExport(Export):
    headers = [
        Field('vendor_house_id', '物件編號'),
        Field('vendor', '租屋平台', fn=Export.lookup_vendor),
        Field('vendor_house_url', '物件網址'),
        Field('created', '物件首次發現時間'),
        Field('updated', '物件最後更新時間'),
        Field('top_region', '縣市', enum=enums.TopRegionType),
        Field('sub_region', '鄉鎮市區', enum=enums.SubRegionType),
        Field('deal_status', '房屋出租狀態', enum=enums.DealStatusType),
        Field('deal_time', '出租大約時間'),
        Field('n_day_deal', '出租所費天數'),
        Field('monthly_price', '月租金'),
        Field('deposit_type', '押金類型', enum=enums.DepositType),
        Field('n_month_deposit', '押金月數'),
        Field('deposit', '押金金額'),
        Field('is_require_management_fee', '需要管理費？'),
        Field('monthly_management_fee', '月管理費'),
        Field('has_parking', '提供車位？'),
        Field('is_require_parking_fee', '需要停車費？'),
        Field('monthly_parking_fee', '月停車費'),
        Field('per_ping_price', '每坪租金（含管理費與停車費）'),
        # Field('detail_dict', '建築類型_原始', field='building_type',
        #     fn=lambda x: x['side_metas'].get('型態', '')),
        Field('building_type', '建築類型', enum=enums.BuildingType),
        Field('property_type', '物件類型', enum=enums.PropertyType),
        Field('is_rooftop', '自報頂加？'),
        # Field('detail_dict', '樓層_原始', field='raw_floor',
        #     fn=lambda x: x['side_metas'].get('樓層', '')),
        Field('floor', '所在樓層'),
        Field('total_floor', '建物樓高'),
        Field('dist_to_highest_floor', '距頂樓層數'),
        # Field('detail_dict', '坪數_原始', field='ping_raw',
        #     fn=lambda x: x['side_metas'].get('坪數', '')),
        Field('floor_ping', '坪數'),
        Field('n_balcony', '陽台數'),
        Field('n_bath_room', '衛浴數'),
        Field('n_bed_room', '房數'),
        Field('n_living_room', '客廳數'),
        Field('apt_feature_code', '格局編碼（陽台/衛浴/房/廳）',
            fn=lambda x: '_{}'.format(x) if x else None),
        # Field('rough_address', '約略住址'),
        # Field('rough_gps', '約略經緯度（未實做）'),
        # Field('detail_dict', '額外費用_原始', field='price_includes'),
        Field('additional_fee', '額外費用_電費？', field='eletricity'),
        Field('additional_fee', '額外費用_水費？', field='water'),
        Field('additional_fee', '額外費用_瓦斯？', field='gas'),
        Field('additional_fee', '額外費用_網路？', field='internet'),
        Field('additional_fee', '額外費用_第四台？', field='cable_tv'),
        # Field('detail_dict', '生活機能_原始', field='living_functions',
        #     fn=lambda x: '/'.join(x['environment'].get('生活機能', []))),
        Field('living_functions', '附近有_學校？', field='school'),
        Field('living_functions', '附近有_公園？', field='park'),
        Field('living_functions', '附近有_百貨公司？', field='dept_store'),
        Field('living_functions', '附近有_超商？', field='conv_store'),
        Field('living_functions', '附近有_傳統市場？', field='traditional_mkt'),
        Field('living_functions', '附近有_夜市？', field='night_mkt'),
        Field('living_functions', '附近有_醫療機構？', field='hospital'),
        # Field('detail_dict', '附近交通_原始', field='transportation',
        #     fn=lambda x: '/'.join(x['environment'].get('附近交通', []))),
        Field('transportation', '附近的捷運站數', field='subway'),
        Field('transportation', '附近的公車站數', field='bus'),
        Field('transportation', '附近的火車站數', field='train'),
        Field('transportation', '附近的高鐵站數', field='hsr'),
        Field('transportation', '附近的公共自行車數（實驗中）', field='public_bike'),
        # Field('detail_dict', '身份限制_原始', field='tenant_restriction',
        #     fn=lambda x: x['top_metas'].get('身份要求', '')),
        Field('has_tenant_restriction', '有身份限制？'),
        Field('has_gender_restriction', '有性別限制？'),
        Field('gender_restriction', '性別限制', enum=enums.GenderType),
        Field('can_cook', '可炊？'),
        Field('allow_pet', '可寵？'),
        Field('has_perperty_registration', '有產權登記？'),
        Field('contact', '刊登者類型', enum=enums.ContactType),
        Field('author', '刊登者編碼'),
        Field('agent_org', '仲介資訊'),
    ]

    def prepare_houses(self, from_date, to_date, only_big6):

        optional_filter = filters.big6 if only_big6 else {}

        dict_fields = {}
        pure_fields = []

        for header in self.headers:
            if header.annotate:
                dict_fields[header.en] = header.annotate
            else:
                pure_fields.append(header.en)

        houses = House.objects.values(
            *pure_fields,
            **dict_fields
        ).filter(
            **optional_filter,
            additional_fee__isnull=False,
            created__lte=to_date,
            crawled_at__gte=from_date
        ).order_by(
            '-id'
        )
        paginator = Paginator(houses, self.page_size)
        return paginator
