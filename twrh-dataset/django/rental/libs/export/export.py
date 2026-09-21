import json
import csv
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from django.db.models import TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce
from django.utils import timezone
from .json_writer import ListWriter
from .field import Field
from rental import vendors as vendor_registry
from rental import enums

# S5 前置：import 時就查 DB 會讓沒有 DB 的環境連 export 模組都載不進來；改讀常數登錄
# （id↔name 與 Vendor 表一致，見 rental/vendors.py）
vendors = {ref.id: ref.name for ref in vendor_registry.REGISTRY}

class Export(ABC):
    headers = []
    vendors = vendors

    def __init__(self):
        # headers 是 class attr，append 會累積到類別上——同一個行程裡實例化兩次
        # （S3a 的 exportcheck 兩路各一個）家具欄就會出現兩遍。每個實例自己一份。
        self.headers = list(self.headers)
        self.facilities = [
            '床', '桌子', '椅子', '電視', '熱水器', '冷氣',
            '沙發', '洗衣機', '衣櫃', '冰箱', '網路', '第四台', '天然瓦斯'
        ]
        self.page_size = 3000

        self.csv_writer = None
        self.print_enum = True
        self.vendor_stats = {'_total': 0}
        self.vendors = {}

        for facility in self.facilities:
            annotate = None
            if facility in ('桌子', '椅子'):
                # 591 2026 模板把桌子、椅子合併成一項「桌椅」——兩欄照舊語意出，
                # 沒有各自的 key 時退回「桌椅」（2026-09-13，schema 1.0 前的 0.3 修正）
                annotate = Coalesce(
                    KeyTextTransform(facility, 'facilities'),
                    KeyTextTransform('桌椅', 'facilities'),
                    output_field=TextField())
            self.headers.append(Field('facilities', '提供家具_{}？'.format(facility),
                                      field=facility, annotate=annotate))

    @classmethod
    def lookup_vendor(cls, vendor_id):
        return cls.vendors[vendor_id]

    def print(self, from_date, to_date, print_enum=True, only_big6=False, outfile='rental_house', export_json=False, use_tf=True):
        print('---- [{}] Export all houses from {} to {} ----'.format(timezone.localtime(), from_date, to_date))

        self.vendor_stats = {'_total': 0}

        self.init_writer(print_enum, outfile)
        paginator = self.prepare_houses(from_date, to_date, only_big6)

        total_houses = paginator.count
        current_done = 0
        list_writer = None

        if export_json:
            list_writer = ListWriter(outfile)
    
        for page_num in paginator.page_range:
            houses = paginator.page(page_num)
            n_raws = self.print_body(houses, print_enum, use_tf, list_writer)
            current_done += n_raws
            print('[{}] we have {}/{} rows'.format(timezone.localtime(), current_done, total_houses))

        if export_json:
            list_writer.close_all()

        with open('{}.json'.format(outfile), 'w') as file:
            json.dump(self.vendor_stats, file, ensure_ascii=False)

        self.csv_h.close()
        print('---- [{}] Export done ----\nData: {}.csv\nStatistics: {}.json\n'.format(timezone.localtime(), outfile, outfile))

    def init_writer(self, print_enum, file_name):
        zh_csv = open('{}.csv'.format(file_name), 'w')

        zh_writer = csv.writer(zh_csv)

        zh_csv_header = []

        for header in self.headers:
            if print_enum and header.enum:
                zh_csv_header.append(header.zh)
                zh_csv_header.append(header.zh + '_coding')
            elif len(header.child_fields) > 0:
                for more_header in header.child_fields:
                    zh_csv_header.append('{}_{}'.format(header.zh, more_header.zh))
            else:
                zh_csv_header.append(header.zh)

        zh_writer.writerow(zh_csv_header)

        self.csv_h = zh_csv
        self.csv_writer = zh_writer

    def decorate_body(self, houses, print_enum, use_tf, list_writer):
        """
        Called before print_body, so we can decorate it.
        Use this method to query etc table to avoid huge foreign table query
        """
        return houses

    def print_body(self, houses, print_enum, use_tf, list_writer):

        houses = self.decorate_body(houses, print_enum, use_tf, list_writer)
        count = 0

        for house in houses:
            vendor_name = self.lookup_vendor(house['vendor'])
            if vendor_name not in self.vendor_stats:
                self.vendor_stats[vendor_name] = 0

            self.vendor_stats[vendor_name] += 1
            self.vendor_stats['_total'] += 1

            row = []
            obj = {}
            for header in self.headers:
                field = header.en
                source = header.source
                if source not in house:
                    row.append(header.to_human(None))
                    obj[field] = header.to_machine(None)
                else:
                    val = header.to_human(house[source], use_tf)
                    json_val = header.to_machine(house[source])

                    if print_enum:
                        obj[field] = json_val
                        row.append(val)
                        if header.enum:
                            if val != '-':
                                obj[field] = header.enum(val).name
                                row.append(header.enum(val).name)
                            else:
                                obj[field] = json_val
                                row.append(val)
                    elif header.child_fields:
                        for more_header in header.child_fields:
                            more_val = more_header.to_human(val, use_tf),
                            more_json_val = more_header.to_machine(val)
                            row.append(more_val)
                            obj['{}_{}'.format(field, more_header['en'])] = more_json_val
                    else:
                        obj[field] = json_val
                        row.append(val)

            self.csv_writer.writerow(row)

            if list_writer:
                try:
                    filename = enums.TopRegionType(house['top_region']).name
                except:
                    filename = 'default'

                list_writer.write(
                    filename, 
                    obj
                )

            count += 1

        return count

    @abstractmethod
    def prepare_houses(self, from_date, to_date, only_big6):
        raise NotImplementedError()
