# 開放台灣民間租屋資料

長期收集各租屋網站、品牌公寓的可公開資訊，清洗後整理成格式統一的資料，供後續有需要的人使用。

- 專案資訊請見 [hackpad](https://g0v.hackpad.tw/Ih7Jp4pUD5y)。


# 程式使用方式與注意事項

本程式還在初期開發階段，任何框架、資料庫定義、API 皆有可能更動。

關於開發的詳細資訊，請參見[專案 wiki ](https://github.com/g0v/tw-rental-house-data/wiki/)

## 資料庫與網頁後端
### 環境需求
1. Python3 + pip

### Peewee -> Django 遷移步驟
1. 理論上可以直接用 Django 內建工具，因為 0001_migration 的內容與 Peewee 完全相同
2. 唯一的例外是 PostgreSQL ，請在遷移完畢後，執行 `python manage.py migratepeewee` ，
   使用方式請參見 `--help`

### 使用方式
```sh
# 安裝相關套件
virtualenv -p python3 .
pip install -r requirements.txt

cd backend
# 設定資料庫（預設使用 sqlite ）
## 詳細資訊請見 [Django 官網](https://docs.djangoproject.com/en/2.0/topics/settings/)
## 如果想用 PostgreSQL 9.3+ ，推薦打開 USE_NATIVE_JSONFIELD ，可以使用內建的 jsonb 
vim backend/settings_local.py

# 設定資料庫
## 使用 --fake-init 可以讓 Django 跳過已存在的 migration script 
## (如果你之前有乖乖把 DB 建好的話)
python manage.py migrate --fake-init
python manage.py loaddata vendors
```

## 爬蟲

### 環境需求
1. Python3 + pip

### 使用方式

確定資料庫準備完成後，執行以下步驟：

```sh
cd crawler

# 設定 Scrapy
cp crawler/settints.sample.py crawler/settings.py
vim crawler/settings.py

# 開始爬資料
./go.sh
```

### 注意事項

1. 請友善對待租屋網站，依其個別網站使用規則容許的方式與頻率來查詢資料，建議可使用 Scrapy 內附的
   [DOWNLOAD_DELAY](https://doc.scrapy.org/en/latest/topics/settings.html#std:setting-DOWNLOAD_DELAY) 或 
   [AUTO_THROTTLING](https://doc.scrapy.org/en/latest/topics/autothrottle.html) 調整爬蟲速度。
2. 爬蟲以收集各網站可散佈的共同資料欄位為主，不會儲存所有網頁上的欄位。
3. 使用者使用本專案提供程式來進行公開資訊的分析與調取，其使用行為及後續資訊的利用行為，
   需符合現行法令的要求且自負其責，包括但不限於個人隱私、資料保護、資訊安全，以及公平競爭等相關規定。
4. 其他事項請參見[授權頁面](LICENSE)。

## 網頁前端

### 環境需求
  1. node 8+

### 使用方式
```sh
# 安裝套件
cd web/ui
npm install

# 啟動開發環境
npm run dev

```

詳細操作方式，請參見 [nuxt](https://nuxtjs.org/)


# 非宅界專案貢獻者

- [Lucien C.H. Lin (林誠夏)](lucien.cc)
- [勞工陣線](http://labor.ngo.tw/) 洪敬舒

