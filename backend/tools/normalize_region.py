import json
from os import path

j2 = json.load(open('{}/319.sub_region.json'.format(
    path.dirname(path.realpath(__file__))
)))

region_dict = {}

for item in j2:
    top = item[1]
    sub = item[0]

    if top not in region_dict:
        region_dict[top] = []

    region_dict[top].append(sub)

ordered_top_region = [
    {"int":  0, "enum": "南投縣"},
    # workaround for existing bug - duplicated top region entry
    # {"int":  1, "enum": "台中市"},
    # {"int":  2, "enum": "台北市"},
    # {"int":  3, "enum": "台南市"},
    # {"int":  4, "enum": "台東縣"},
    {"int":  5, "enum": "嘉義市"},
    {"int":  6, "enum": "嘉義縣"},
    {"int":  7, "enum": "基隆市"},
    {"int":  8, "enum": "宜蘭縣"},
    {"int":  9, "enum": "屏東縣"},
    {"int": 10, "enum": "彰化縣"},
    {"int": 11, "enum": "新北市"},
    {"int": 12, "enum": "新竹市"},
    {"int": 13, "enum": "新竹縣"},
    {"int": 14, "enum": "桃園市"},
    {"int": 15, "enum": "澎湖縣"},
    {"int": 16, "enum": "臺中市"},
    {"int": 17, "enum": "臺北市"},
    {"int": 18, "enum": "臺南市"},
    {"int": 19, "enum": "臺東縣"},
    {"int": 20, "enum": "花蓮縣"},
    {"int": 21, "enum": "苗栗縣"},
    {"int": 22, "enum": "連江縣"},
    {"int": 23, "enum": "金門縣"},
    {"int": 24, "enum": "雲林縣"},
    {"int": 25, "enum": "高雄市"}
]

output = {
    'top_region': [],
    'sub_region': []
}

for tokens in ordered_top_region:
    i = tokens['int']
    top = tokens['enum']
    top2 = top.replace('臺', '台')

    if top2 is not top:
        output['top_region'].append((top2, i))

    output['top_region'].append((top, i))

    for (j, sub) in enumerate(sorted(region_dict[top])):
        code = i * 100 + j
        sub2 = sub.replace('臺', '台')

        if top2 is not top:
            key = '{}{}'.format(top2, sub)
            output['sub_region'].append((key, code))

            if sub2 is not sub:
                key = '{}{}'.format(top2, sub2)
                output['sub_region'].append((key, code))

        key = '{}{}'.format(top, sub)
        output['sub_region'].append((key, code))

        if sub2 is not sub:
            key = '{}{}'.format(top, sub2)
            output['sub_region'].append((key, code))

with open('tw_regions.json', 'w', encoding='utf8') as f:
    json.dump(output, f, ensure_ascii=False)
