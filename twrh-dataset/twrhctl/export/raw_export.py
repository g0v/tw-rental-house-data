'''Raw export（twrhctl 版：django/rental/libs/export/raw_export.py 的欄位定義＋snapshot 讀取端；
DB 路徑（House queryset）隨 DB 退場不搬）。'''
import math

from rental import vendors as vendor_registry
from rental import enums
from . import snapshot_source
from .export import Export
from .field import Field


class Paginator:
    '''django.core.paginator.Paginator 的最小等價物（Export.print 只用 count／page_range／page）。'''

    def __init__(self, object_list, per_page):
        self.object_list = object_list
        self.per_page = per_page
        self.count = len(object_list)
        self.num_pages = max(1, math.ceil(self.count / per_page))   # allow_empty_first_page
        self.page_range = range(1, self.num_pages + 1)

    def page(self, number):
        start = (number - 1) * self.per_page
        return self.object_list[start:start + self.per_page]


class RawExport(Export):
    headers = [
        Field('vendor_house_id', '物件編號'),
        Field('vendor', '租屋平台', fn=Export.lookup_vendor),
        # 物件網址：2026 改版後 detail 解析不再帶 URL、House.vendor_house_url 恆空
        # （202603／202608 月包整欄 '-'），改由 vendor 樣板生成；其他 vendor 退回存值
        Field('vendor_house_url', '物件網址', source='house_url'),
        Field('created', '物件首次發現時間'),
        Field('updated', '物件最後更新時間'),
        Field('top_region', '縣市', enum=enums.TopRegionType),
        Field('sub_region', '鄉鎮市區', enum=enums.SubRegionType),
        Field('rough_coordinate', '約略地點_x', en='rough_coordinate_x', fn=lambda p: p.x if p else None),
        Field('rough_coordinate', '約略地點_y', en='rough_coordinate_y', fn=lambda p: p.y if p else None),
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

    # S3a：snapshot 讀取端要的 parquet 欄（**不含 vendor_extra／imgs**——月窗
    # 十幾萬列帶著整份 detail_dict 會吃掉 publisher 的 4 GB）
    snapshot_columns = [
        'vendor_house_id', 'top_region', 'sub_region', 'deal_status', 'deal_time',
        'n_day_deal', 'monthly_price', 'deposit_type', 'n_month_deposit', 'deposit',
        'is_require_management_fee', 'monthly_management_fee', 'has_parking',
        'is_require_parking_fee', 'monthly_parking_fee', 'per_ping_price',
        'building_type', 'property_type', 'is_rooftop', 'floor', 'total_floor',
        'dist_to_highest_floor', 'floor_ping', 'n_balcony', 'n_bath_room',
        'n_bed_room', 'n_living_room', 'apt_feature_code', 'has_tenant_restriction',
        'has_gender_restriction', 'gender_restriction', 'can_cook', 'allow_pet',
        'has_perperty_registration', 'contact', 'agent_org', 'author_key', 'crawled_at',
        'rough_lat', 'rough_lng', 'additional_fee', 'living_functions',
        'transportation', 'facilities',
        'first_seen_at', 'last_seen_at', 'last_detail_at',
    ]

    def __init__(self, source='snapshot'):
        super().__init__()
        self.source = source

    def decorate_body(self, houses, print_enum, use_tf, list_writer):
        # snapshot 的 JSON 欄是整包字串，展平成 DB 路徑 KeyTextTransform 的同名 key
        if self.source != 'snapshot':
            return houses
        return [snapshot_source.decorate_json_keys(row, self.headers)
                for row in houses]

    def prepare_snapshot_houses(self, from_date, to_date, only_big6):
        # S3a：改讀 4c 的 snapshot 分區，不碰 House
        if only_big6:
            raise NotImplementedError('snapshot 路徑尚未支援 -b6（月包不用它）')
        vendor = vendor_registry.get('591 租屋網', orm=False)
        window = snapshot_source.SnapshotWindow(
            from_date, to_date, vendor='591',
            vendor_id=vendor.id if vendor else None,
            columns=self.snapshot_columns)
        print('---- snapshot 路徑：{} 天分區、{} 戶（列序＝物件編號遞減）----'.format(
            len(window.days), len(window)))
        return Paginator(window, self.page_size)

    def prepare_houses(self, from_date, to_date, only_big6):
        if self.source != 'snapshot':
            raise NotImplementedError('twrhctl export 只有 snapshot 路徑（DB 已退場）')
        return self.prepare_snapshot_houses(from_date, to_date, only_big6)
