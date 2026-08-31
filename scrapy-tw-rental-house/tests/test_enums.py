from scrapy_twrh.spiders import enums


def test_sub_region_emei_canonical_is_official_name():
    '''峨眉鄉：官方名為 canonical、591 的「峨嵋鄉」為 alias（同值 1304）。

    591 介面用的是「峨嵋鄉」（typo），發布資料集歷來用官方名「峨眉鄉」。
    Enum 以先出現者為 canonical——json 內順序即契約，這裡釘住它（dx 4-1）。
    兩個名字都必須查得到：parser 拿 591 字串 lookup 走 alias。
    '''
    official = enums.SubRegionType['新竹縣峨眉鄉']
    from_591 = enums.SubRegionType['新竹縣峨嵋鄉']
    assert official is from_591
    assert official.value == 1304
    assert official.name == '新竹縣峨眉鄉'


def test_sub_region_names_match_top_region():
    '''sub_region 名稱都以所屬 top_region 名稱開頭（lookup 組字串的前提）。'''
    top_names = tuple(t.name for t in enums.TopRegionType)
    for member in enums.SubRegionType:
        assert member.name.startswith(top_names), member.name
