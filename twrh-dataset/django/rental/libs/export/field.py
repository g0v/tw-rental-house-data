from django.db.models.fields.json import KeyTextTransform
from datetime import datetime
from django.utils import timezone

class Field():
    def __init__(
        self,
        column,
        zh,
        en=None,
        field=None,
        enum=None,
        annotate=None,
        fn=None,
        child_fields=[],
        source=None):

        self.column = column
        self.zh = zh
        self.en = en if en else column
        self.field = field
        self.annotate = annotate
        self.fn = fn
        self.child_fields = []

        if field:
            self.en = '{}_{}'.format(self.en, field)

        # 查詢結果裡讀哪個 key；預設同 en（含 field 後綴）。annotate 名不能與 model
        # 欄位同名（Django 擋 conflicts with a field），要覆寫既有欄位時用它另起名
        self.source = source or self.en

        if not annotate and self.field:
            self.annotate = KeyTextTransform(self.field, self.column)

        for child in child_fields:
            self.child_fields.append(Field(**child))

    def to_human(self, val, use_tf=True):

        if self.fn:
            val = self.fn(val)

        if isinstance(val, datetime):
            val = timezone.localtime(val).strftime('%Y-%m-%d %H:%M:%S %Z')
        elif val == '' or val is None:
            val = '-'
        elif val is True or val == 'true':
            val = 'T' if use_tf else 1
        elif val is False or val == 'false':
            val = 'F' if use_tf else 0

        return val

    def to_machine(self, val):
        if self.fn:
            val = self.fn(val)

        if isinstance(val, datetime):
            pass
        elif val == '' or val is None:
            val = None
        elif val is True or val == 'true':
            val = True
        elif val is False or val == 'false':
            val = False

        return val
