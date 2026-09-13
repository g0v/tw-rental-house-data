'''GenericHouseItem 進 pipeline 前的欄位衛生（2026-09-13，schema 1.0 草案 §1 P1／P3）。

pipeline 對 item 的每個 key 都 setattr 到 House／HouseTS，所以「item 帶了什麼 key」
就是「會覆寫什麼欄」。兩個已知的反向覆寫在這裡擋：

- list 頁的 tag（電梯／陽台／可報稅／租金補貼…）被 package 轉成 facilities dict，
  每個 list 日都蓋掉 detail 頁抓到的完整家具清單；detail 才是 facilities 的來源，
  list item 不帶這個 key。tag 原文之後走 1.0 的 tags 欄，raw list HTML 每天有存。
- detail 解析器目前不抓地址（TODO），item 的 rough_address 恆 None，反過來蓋掉 list
  給的街道級地址；值為 None 的 key 不該進 pipeline。

兩個函數都是就地修改並回傳同一個 item，方便在 yield 前串用。
'''

LIST_DROP_KEYS = ('facilities',)


def strip_list_item(item):
    '''list 階段的 GenericHouseItem：拿掉只該由 detail 決定的欄。'''
    for key in LIST_DROP_KEYS:
        if key in item:
            del item[key]
    return item


def strip_detail_item(item):
    '''detail 階段的 GenericHouseItem：值為 None 的 rough_address 不覆寫既有值。'''
    if 'rough_address' in item and item['rough_address'] is None:
        del item['rough_address']
    return item
