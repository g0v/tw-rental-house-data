# 資料合併、驗證小幫手

## 環境需求

1. [Clickhouse local](https://clickhouse.com/docs/en/operations/utilities/clickhouse-local)

## 合併小幫手

小幫手將使用 Clickhouse local ，將多個單月的原始 CSV ，合併為跨月的原始 +
去除重複資料的資料集。自 2023 開始，本資料集的季度、年度資料，也是使用這支程式製作。

準備工作：

1. 將要合併的所有 `zip` ，例如 `[YYYYMM][CSV][Raw] TW-Rental-Data.zip`，放到同一個資料夾中，比如說 `source/`
2. 確定要產稱的檔案名稱前綴，例如 2025Q1

```bash
./merge-and-dedup.sh <source dir> <YYYYOO>
```

以 `YYYYOO` = `2025Q1` 為例，執行完畢後，就可在資料夾中看到：

1. `[2025Q1][CSV][Raw] TW-Rental-Data.zip`
2. `[2025Q1][CSV][Deduplicated] TW-Rental-Data.zip`

## 驗證小幫手

計算單月資料集中，CSV 、JSON 物件數量差異，並匯入編碼表的小幫手。

使用前，請先確定下載的 `.zip` ，和 `check.sh` 在同一個資料夾中。

```bash
check.sh <YYYYMM>
```

