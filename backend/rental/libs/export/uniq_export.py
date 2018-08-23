from django.db.models.functions import Cast
from django.db.models import Count, Max, Min, Avg, TextField
from django.core.paginator import Paginator

from .field import Field
from .export import Export
from rental.libs import filters
from rental.models import House, HouseEtc
from rental import enums

class UniqExport(Export):
    headers = [
        Field('id', '重複物件數', en='n_duplicate', annotate=Count('id')),
        Field('vendor_house_id', '最大物件編號', en='max_house_id', annotate=Max('vendor_house_id')),
        Field('vendor_house_id', '最小物件編號', en='min_house_id', annotate=Min('vendor_house_id')),
        Field('created', '最大物件首次發現時間', en='max_created', annotate=Max('created')),
        Field('created', '最小物件首次發現時間', en='min_created', annotate=Min('created')),
        Field('vendor', '租屋平台', fn=Export.lookup_vendor),
        Field('top_region', '縣市', enum=enums.TopRegionType),
        Field('sub_region', '鄉鎮市區', enum=enums.SubRegionType),
        Field('deal_status', '房屋曾出租過', en='has_dealt', enum=enums.DealStatusType, annotate=Max('deal_status')),
        Field('deal_time', '最後出租時間', en='max_deal_time', annotate=Max('deal_time')),
        Field('n_day_deal', '最大出租所費天數', en='max_n_day_deal', annotate=Max('n_day_deal')),
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
        Field('building_type', '建築類型', enum=enums.BuildingType),
        Field('property_type', '物件類型', enum=enums.PropertyType),
        Field('is_rooftop', '自報頂加？'),
        Field('floor', '所在樓層'),
        Field('total_floor', '建物樓高'),
        Field('dist_to_highest_floor', '距頂樓層數'),
        Field('floor_ping', '坪數'),
        Field('n_balcony', '陽台數'),
        Field('n_bath_room', '衛浴數'),
        Field('n_bed_room', '房數'),
        Field('n_living_room', '客廳數'),
        Field('apt_feature_code', '格局編碼（陽台/衛浴/房/廳）', fn=lambda x: '_{}'.format(x) if x else None),
        Field('additional_fee', '額外費用_電費？', field='eletricity'),
        Field('additional_fee', '額外費用_水費？', field='water'),
        Field('additional_fee', '額外費用_瓦斯？', field='gas',),
        Field('additional_fee', '額外費用_網路？', field='internet'),
        Field('additional_fee', '額外費用_第四台？', field='cable_tv'),
        Field('living_functions', '附近有_學校？', field='school'),
        Field('living_functions', '附近有_公園？', field='park'),
        Field('living_functions', '附近有_百貨公司？', field='dept_store'),
        Field('living_functions', '附近有_超商？', field='conv_store'),
        Field('living_functions', '附近有_傳統市場？', field='traditional_mkt'),
        Field('living_functions', '附近有_夜市？', field='night_mkt'),
        Field('living_functions', '附近有_醫療機構？', field='hospital'),
        Field('transportation', '附近的捷運站數', field='subway'),
        Field('transportation', '附近的公車站數', field='bus'),
        Field('transportation', '附近的火車站數', field='train'),
        Field('transportation', '附近的高鐵站數', field='hsr'),
        Field('transportation', '附近的公共自行車數（實驗中）', field='public_bike'),
        # {
        #     'en': 'tenant_restriction',
        #     '身份限制',
        #     annotate=KeyTextTransform('身份要求', KeyTransform('top_metas', 'etc__detail_dict')),
        #     fn=lambda x: [] if x is None else json.loads(x),
        #     'expand_header': [
        #         Field('student', '學生？', fn=lambda field_value: '學生' in field_value),
        #         Field('office_worker', '上班族？', fn=lambda field_value: '上班族' in field_value),
        #         Field('family', '家庭？', fn=lambda field_value: '家庭' in field_value)
        #     ]
        # ),
        Field('has_tenant_restriction', '有身份限制？'),
        Field('has_gender_restriction', '有性別限制？'),
        Field('gender_restriction', '性別限制', enum=enums.GenderType),
        Field('can_cook', '可炊？'),
        Field('allow_pet', '可寵？'),
        Field('has_perperty_registration', '有產權登記？'),
        Field('contact', '刊登者類型', enum=enums.ContactType),
        Field('author_id', '最大刊登者編碼', en='max_author_id', annotate=Max(Cast('author_id', TextField()))),
        Field('agent_org', '仲介資訊'),
    ]

    def prepare_houses(self, from_date, to_date, only_big6):
        search_values = []
        search_annotates = {}

        for header in self.headers:
            if header.annotate:
                search_annotates[header.en] = header.annotate
            else:
                search_values.append(header.column)


        optional_filter = filters.big6 if only_big6 else {}

        houses = House.objects.values(
            *search_values
        ).annotate(
            **search_annotates
        ).filter(
            additional_fee__isnull=False,
            **optional_filter,
            **filters.should_be_house,
            created__lte=to_date,
            crawled_at__gte=from_date,
        ).order_by(
            'max_house_id'
        )

        paginator = Paginator(houses, self.page_size)
        return paginator