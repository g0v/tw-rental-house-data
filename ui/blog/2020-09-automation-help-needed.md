---
title: 拖稿半年資料釋出，徵求自動化小幫手
author: ddio
created: 2020-09-03
cover: /imgs/blog/2020-09.png
config: 
  html: true
tags:
  - 關於
  - 定期紀錄
---

封面圖片源自[曼努](https://medium.com/wumanzoo/)製作的[2020 台北捷運房租地圖](https://medium.com/wumanzoo/2020-taipei-metro-rent-map-dc3a8c45289d)，資料由 [Jheng-Yu Lee](https://medium.com/@jhengyulee) 整理，資料原始出處來自這個資料集。

這半年因為各種忙，像是開始跳坑作[居住議題的開源社群](https://g0v.hackmd.io/@ddio/rentea-tue)、幫忙 [g0v 雙年會](https://summit.g0v.tw/2020/)的一小部份網站，還有幾個組織的數位專案，租屋資料僅維持最低程度的運作，確定機器人有乖乖爬資料、空間足夠，但新出現的警告訊息，
以及整理資料、放上網站，就和沒折的衣服一樣，一直拿不起力氣處理。

沒時間、沒力氣時，更新就會暫停，這個問題其實不難處理，但因為製作[解法本身](https://github.com/g0v/tw-rental-house-data/issues/47)，也需要額外的力氣與時間，因此全自動更新網站的事情，就從去年底一路拖到現在。曾經有想過是否要開個捐款連結，募到一定金額，就來實做新功能，但覺得拿錢辦事，也還是有些壓力，所以與其募資，不如不人力好了 XD

開放台灣租屋資料是台灣目前唯一的租屋公開資料集，程式使用開放原始碼，機器人使用 Python + Scrapy 製作。歡迎對租屋議題有興趣的人，一起來協助這個專案，讓它可以收集更多元的台灣租屋平台的資料，為台灣的居住環境，貢獻一份力量。

目前專案最需要的工作包含：

1. [全自動發佈定期資料](https://github.com/g0v/tw-rental-house-data/issues/47)
2. [新增 591 以外的各種租屋刊登網站](https://github.com/g0v/tw-rental-house-data/labels/data-source)

另外，也可以翻翻 [Github 裡的其他工作](https://github.com/g0v/tw-rental-house-data/issues)，看看有沒有興趣認領～
