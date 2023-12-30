# 開放台灣民間租屋資料

長期收集各租屋網站、品牌公寓的可公開資訊，清洗後整理成格式統一的資料，供後續有需要的人使用。

- 專案資訊請見 [hackpad](https://g0v.hackpad.tw/Ih7Jp4pUD5y)。
- 爬蟲套件請見 [PyPI](https://pypi.org/project/scrapy-tw-rental-house/)

## 程式使用方式與注意事項

本專案總共分為三部份：

1. `scrapy-tw-rental-house` - 爬蟲本人，只需要 Scrapy 即可使用，不綁資料庫
   - [原始碼](https://github.com/g0v/tw-rental-house-data/tree/master/scrapy-tw-rental-house)
   - [套件網頁](https://pypi.org/project/scrapy-tw-rental-house/)
2. `twrh-dataset` - 完整的開放資料流程，包含爬蟲、資料儲存
   - [原始碼](https://github.com/g0v/tw-rental-house-data/tree/master/twrh-dataset)
3. `ui` - 開放台灣租屋資料網站
   - [原始碼](https://github.com/g0v/tw-rental-house-data/tree/master/twrh-dataset)
   - [網站](https://rentalhouse.g0v.ddio.io/)

關於開發的詳細資訊，請參見[專案 wiki](https://github.com/g0v/tw-rental-house-data/wiki/)


## 非宅界專案貢獻者

- [Lucien C.H. Lin (林誠夏)](lucien.cc)
- [勞工陣線](http://labor.ngo.tw/) 洪敬舒
