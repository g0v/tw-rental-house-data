---
title: 開放台灣租屋資料處理流程
author: ddio
created: 2024-03-10
cover: /imgs/blog/pipeline-2024.jpeg
tags:
  - 關於
  - 技術文件
---

寫出網路爬蟲，是一回事，但要能夠長期維運，並將它轉換為資料集，則完全是另一項工作。這篇文章將介紹我們如何處理開放台灣租屋資料（以下簡稱開租）的流程。

開租總共使用三組流程，並將中繼、最終資料，存在三種資料表中。

<!--more-->

## 每日例行工作 - 儲存前日所有租屋平台的物件最新資訊

![每日例行工作](/imgs/blog/twrh-daily-pipeline.png)

這是開租的核心工作，每日清晨，系統自動甦醒後，會以各租屋平台為單位

1. 載入該平台設定
2. 擷取平台的物件清單，若有除了 ID 以外的資訊，則會一併儲存在未正規劃的資料表中，以盡量保留原始資料
3. 根據當日新增的清單，再合併資料庫中尚未標示為關閉的物件，逐一擷取物件的詳細資訊，並儲存至未正規化的資料表中
4. 將未正規化的資料表，轉換為正規化的資料表，並分別儲存至
   1. 每日歷史表，以供物件狀態等，需要多日資料才能判讀資訊分析
   2. 物件總覽表，供後續長天期分析

附帶一題，雖然系統架構上，開租支援多租屋平台資料紀錄，但由於缺乏開發資源，截至 2024 年三月為止，僅有 591 租屋網，是有完整執行的。

## 三種資料表 - 是否正規劃 x 每日或最新總覽

![資料表圖例](/imgs/blog/twrh-table-types.png)

由每日例行工作可知，開租的資料表分為三種，並用兩項屬性來區分：

1. 是否正規化
   - 由於開租希望能夠彙整多個平台的資訊，因此會將各平台的資料，轉為統一個資料格式，方便讓使用者進行資料分析
   - 但正規劃的過程中，必定會刪除、修改部份資訊，因此我們也會保留原始資料，若將來[資料集格式](/about-data-set/)調整時，也能使用原始資料（未正歸化資料），更新資料集
   - 由於未正規化資料表，可能包含不適合公開的資訊，例如詳細的地址，因此並不會提供給外界使用
2. 每日留存，或是僅保留最新資訊
   - 資料庫中，會以日期為單位，儲存最近 60 天的資料，以判斷物件的狀態，例如是否已出租，並作為事後疑難排解的依據
   - 但由於開租的目的是提供長期資料分析，因此也會將每日的資料，轉換為最新總覽，每個物件僅保留最後的資料，以供使用者進行資料分析

由這兩個屬性，我們可以得到三種資料表：

1. **未正規化的最新總覽**，僅供內部流程暫存、分析、資料復原使用
2. **正規化的每日歷史資訊** ，僅供內部流程暫存、分析、資料復原使用
3. **正規化的最新總覽**，也是開租釋出的[資料集](/download/)

## 每月例行工作 - 整併當月所有租屋平台的物件資訊

![每月例行工作](/imgs/blog/twrh-monthly-pipeline.png)

每月例行工作，是為了將每日例行工作的資料，整併成一個月的資料，並將其轉換為最新總覽，以供使用者進行資料分析。

為了節省資料庫計算資源，每月例行工作，僅使用資料庫匯出原始資料，後續則使用 ClickHouse ，製作消除重複住宅資料集。

## 每季、年的例行工作 - 整併當季、年所有租屋平台的物件資訊

![每季、年例行工作](/imgs/blog/twrh-quarterly-pipeline.png)

由於每季、年的資料量過大，從原始資料開始，我們就會使用 ClickHouse 進行資料整併，並將其轉換為最新總覽、消除重複住宅資料集，以供使用者進行資料分析。
