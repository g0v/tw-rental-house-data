# 分佈不變量 baseline（L3 drift detector 斷言基準）

`twrh survey <縣市> --baseline baselines/<檔>.json` 會把本次 survey 的
分佈不變量（樓層中位數、建物／物件型態占比、頂加率、關鍵欄位填充率）
與 baseline 比對，超出容許差即以非零值退出——這就是 L3 nightly 的斷言核心
（docs/dx-roadmap.md 3-3）。

- **`*.hualien.json`** — L3 nightly 的目標城市（物件型態多元，能踩到各 parser 分支）。
- **`*.national.json`** — 全量爬取（go.sh）後的驗收基準，樣本門檻 10,000，
  survey 單一縣市不會觸及；供全量 export 層級的比對使用。

## 原則

- 斷言下在**比率與中位數**，永不下在特定 ID 或特定值（591 資料每天變、ID 不會永遠有效）。
- 比對**雙向**：填充率「變好」也算漂移——頂加率歸零＝parser 斷了某分支；
  暴增＝591 版面或市場有變。兩者都需要人看。
- 樣本 < `min_samples` 時跳過硬斷言，避免抽樣噪音造成 nightly 誤報。
- baseline **刻意不隨每次 survey 自動更新**；漂移確認是市場自然變化後，
  把當次 survey 報告的 `invariants` 段落抄成新檔（保留舊檔、檔名帶日期）。

## 來源

2026-08-26 首次本機全台全量（55,400 筆 raw export）與 2024-09 公開資料集做
縣市級分佈比對驗證通過後產出。數值皆為聚合統計，不含任何個別物件資訊。
