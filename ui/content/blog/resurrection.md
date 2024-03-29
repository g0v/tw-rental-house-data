---
title: 開放租屋資料即將復活！
author: ddio
created: 2022-08-16
cover: /imgs/blog/resurrection-og.jpg
config: 
  html: true
tags:
  - 關於
  - 定期紀錄
---

感謝大家的關心，長話短說，2021-05 後的資料都還在，只是還沒上傳。預計八月底左右，就會上架 2021-06 到目前為止的所有資料！

<!--more-->

## 完整解釋

從去年五月開始，本資料集碰到了以下的問題：

1. `2021-06 ~ 2021-10` 591 租屋網，從 2021-06 開始改版，並在同年 9 月關閉舊有的資料讀取方式，導致資料集遺失了部份 10 月的資料。
2. `2021-06 ~ 2022-03` 資料集的主要維護者 ddio ，2021 整年掉到[另一個大坑中](https://g0v.hackmd.io/@ddio/corent)，從 6 月開始，就沒時間照顧網站
3. `2021-10 ~ 現在` 爬資料的機器人，在 10 月底時修復，但因為上述理由，一直沒空調查資料遺失的程度，因此也沒有上傳資料
4. `2022-03 ~ 現在` ddio 爬出坑後，忙者補各種欠下的工作

總結來說，一開始是因為 591 改版，加上 ddio 這一年多各種忙，再加上資料集更新，還需要不少手工作業，所以便一直拖到現在。

這個夏天，ddio 會依序進行以下幾件事：

1. [更新網站架構](https://github.com/g0v/tw-rental-house-data/issues/115)，並[設計新的爬蟲架構，讓它更容易自動化](https://github.com/g0v/tw-rental-house-data/issues/47)（已完成）
2. 分析 2021-09 591 改版時，造成資料遺失狀況，並以文章說明
3. 上傳 2021-10 ~ 2021-12 的所有資料，包含 2021 Q4 以及全年資料
4. 上傳 2022-01 ~ 2022-08 的所有資料，包含 2022 Q1 、Q2
5. 把爬蟲搬到較有管理彈性的地方
6. 依據計畫，實做[自動更新的流程](https://github.com/g0v/tw-rental-house-data/issues/47)

目前目標是在八月底時，完成前四項。

如果有什麼建議，會想一起幫忙讓爬蟲更新更自動的，歡迎加入這個專案～
