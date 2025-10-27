# 開放台灣民間租屋資料

長期收集各租屋網站、品牌公寓的可公開資訊，清洗後整理成格式統一的資料，供後續有需要的人使用。

- 專案資訊請見 [hackpad](https://g0v.hackpad.tw/Ih7Jp4pUD5y)。
- 爬蟲套件請見 [PyPI](https://pypi.org/project/scrapy-tw-rental-house/)

## 爬蟲本人

關於環境需求與使用方式，請見[套件網頁](https://pypi.org/project/scrapy-tw-rental-house/)。

## 資料庫與網頁後端

### 環境需求

1. Python3.10+
2. [Poetry](https://python-poetry.org/)
3. [PostgreSQL](https://www.postgresql.org) 15+
   - 使用 PostgresSQL 以外的資料庫時，爬蟲可以順利執行，但使用內建的匯出指令時無法用 `-u --unique` 去除重複物件
5. GeoDjango ，目前[主要的關聯式資料庫都有支援](https://docs.djangoproject.com/en/5.0/ref/contrib/gis/db-api/)
   - 關於如何準備 GeoDjango 所需的系統環境，請參見[官方文件](https://docs.djangoproject.com/en/5.0/ref/contrib/gis/install/)

#### 資料庫設定

```sh
# 使用 poetry 安裝相關套件
poetry install
poetry run playwright install chromium

# 進入 virtualenv
poetry shell

cd backend
# 設定資料庫（預設使用 sqlite）
## 詳細資訊請見 [Django 官網](https://docs.djangoproject.com/en/2.0/topics/settings/)
vim backend/settings_local.py

# 設定資料庫
## 使用 --fake-init 可以讓 Django 跳過已存在的 migration script 
python manage.py migrate
python manage.py loaddata vendors
```

#### 爬蟲使用方式

確定資料庫準備完成後，執行以下步驟：

```sh
cd crawler

# 設定 Scrapy
cp crawler/settings.sample.py crawler/settings.py
vim crawler/settings.py

# 開始爬資料
./go.sh
```

#### 資料匯出

```bash
poetry run backend/manage.py export --help
```

#### 注意事項

1. 請友善對待租屋網站，依其個別網站使用規則容許的方式與頻率來查詢資料，建議可使用 Scrapy 內附的
   [DOWNLOAD_DELAY](https://doc.scrapy.org/en/latest/topics/settings.html#std:setting-DOWNLOAD_DELAY) 或 
   [AUTO_THROTTLING](https://doc.scrapy.org/en/latest/topics/autothrottle.html) 調整爬蟲速度。
2. 爬蟲以收集各網站可散佈的共同資料欄位為主，不會儲存所有網頁上的欄位。
3. 使用者使用本專案提供程式來進行公開資訊的分析與調取，其使用行為及後續資訊的利用行為，
   需符合現行法令的要求且自負其責，包括但不限於個人隱私、資料保護、資訊安全，以及公平競爭等相關規定。
4. 其他事項請參見[授權頁面](LICENSE)。

