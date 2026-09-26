import datetime
import decimal
import json
import uuid


class DjangoJSONEncoder(json.JSONEncoder):
    '''django.core.serializers.json.DjangoJSONEncoder 的等價物（輸出逐字相同：datetime 毫秒截斷、
    UTC 寫成 Z；date／time isoformat；Decimal／UUID 轉字串）。'''

    def default(self, o):
        if isinstance(o, datetime.datetime):
            r = o.isoformat()
            if o.microsecond:
                r = r[:23] + r[26:]
            if r.endswith('+00:00'):
                r = r.removesuffix('+00:00') + 'Z'
            return r
        if isinstance(o, datetime.date):
            return o.isoformat()
        if isinstance(o, datetime.time):
            if o.utcoffset() is not None:
                raise ValueError("JSON can't represent timezone-aware times.")
            r = o.isoformat()
            if o.microsecond:
                r = r[:12]
            return r
        if isinstance(o, (decimal.Decimal, uuid.UUID)):
            return str(o)
        return super().default(o)

class ListWriter():
    def __init__(self, file_prefix):
        self.__file_prefix = file_prefix
        self.__files = {}

    def write(self, filename, row=None, last_line=False):
        if filename not in self.__files:
            fh = open('{}_{}.json'.format(self.__file_prefix, filename), 'w')
            self.__files[filename] = {
                'fh': fh,
                'last': row
            }
            fh.write('[\n')
        elif self.__files[filename]['last']:
            f = self.__files[filename]
            fh = f['fh']
            join_token = '' if last_line else ','
            json_str = json.dumps(
                f['last'],
                cls=DjangoJSONEncoder,
                ensure_ascii=False,
                sort_keys=True
            )
            fh.write('{}{}\n'.format(json_str, join_token))
            f['last'] = row

    def close_all(self):
        for filename in self.__files:
            self.write(filename, last_line=True)
            fh = self.__files[filename]['fh']
            fh.write(']')
            fh.close()


    