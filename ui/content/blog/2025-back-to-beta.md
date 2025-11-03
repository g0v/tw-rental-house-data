---
title: 開租即將再次復活
author: ddio
created: 2025-10-28
cover: /imgs/blog/2025-back-to-beta.png
tags:
  - 資料品質
  - 封面圖片使用 AI 生成  
---

在歷經 2025 年的多輪修復後，開放台灣租屋資料，已經完成主要爬蟲功能的重建，並將從十月開始，開放試爬的資料集，希望能在年底前，恢復到穩定運作的狀態。

<!--more-->

## 目前狀態

1. `已完成` 爬蟲核心邏輯已修復完畢，並更新至 [scrapy-tw-rental-house 2.1.3 @PyPI](https://pypi.org/project/scrapy-tw-rental-house/)
2. `已完成` 每日例行工作邏輯也修復完畢，可順利執行。若有需求者，請參見 [twrh-dataset@Github](https://github.com/g0v/tw-rental-house-data/tree/master/twrh-dataset)
3. `待處理` 由於 591 防爬蟲機制日趨嚴格，資料收集成本漸增，需要調整既有流程，在維持資料品質，以及降低開銷之間，取得平衡

## 關於試爬資料集

試爬期間，會和過去有所不同，主要差異如下：

1. 不會每天爬，目前預計每週爬一次，因此部份欄位，例如出租狀態，資料與時間，可能會有較大落差
2. 由於爬蟲仍在調整中，資料品質可能不如以往穩定，請使用者在使用資料時，務必多加留意

如果發現資料有明顯錯誤，歡迎回報至 [GitHub Issues](https://github.com/g0v/tw-rental-house-data/issues)，或是寄信至 open-tw-rental-house@ddio.io

