import json

j2 = json.load(open('./319.sub_region.json'))

region_dict = {}

for item in j2:
    top = item[1]
    top2 = top.replace('臺', '台')
    sub = item[0]

    if top not in region_dict:
        region_dict[top] = []
        region_dict[top2] = []

    region_dict[top].append(sub)
    if top is not top2:
        region_dict[top2].append(sub)

output = {
    'top_region': [],
    'sub_region': []
}

for (i, top) in enumerate(sorted(region_dict)):
    top2 = top.replace('臺', '台')

    if top2 is not top:
        output['top_region'].append({
            'int': i,
            'enum': top2
        })

    output['top_region'].append({
        'int': i,
        'enum': top
    })

    for (j, sub) in enumerate(sorted(region_dict[top])):
        code = i * 100 + j
        sub2 = sub.replace('臺', '台')

        if top2 is not top:
            output['sub_region'].append({
                'int': code,
                'enum': '{}{}'.format(top2, sub)
            })

            if sub2 is not sub:
                output['sub_region'].append({
                    'int': code,
                    'enum': '{}{}'.format(top2, sub2)
                })

        output['sub_region'].append({
            'int': code,
            'enum': '{}{}'.format(top, sub)
        })

        if sub2 is not sub:
            output['sub_region'].append({
                'int': code,
                'enum': '{}{}'.format(top, sub2)
            })

with open('tw_regions.json', 'w', encoding='utf8') as f:
    json.dump(output, f, ensure_ascii=False)
