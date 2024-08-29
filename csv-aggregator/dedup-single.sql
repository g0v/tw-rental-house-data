SET format_csv_null_representation = '-';

select 
count("物件編號") "重複物件數",
max("物件編號") "最大物件編號",
min("物件編號") "最小物件編號",
max("物件首次發現時間") "最大物件首次發現時間",
min("物件首次發現時間") "最小物件首次發現時間",
max("物件最後更新時間") "物件最後更新時間",
"租屋平台", "縣市", "鄉鎮市區",
anyHeavy("約略地點_x") "常見約略地點_x",
anyHeavy("約略地點_y") "常見約略地點_y",
max("房屋出租狀態") "房屋曾出租過",
max("出租大約時間") "最後出租時間",
max("出租所費天數") "最大出租所費天數",
"月租金", 
"押金類型", "押金月數", "押金金額", "需要管理費？", "月管理費", 
"提供車位？", "需要停車費？", "月停車費", "每坪租金（含管理費與停車費）",
"建築類型", "物件類型", "自報頂加？", "所在樓層", "建物樓高", "距頂樓層數",
"坪數", "陽台數", "衛浴數", "房數", "客廳數", "格局編碼（陽台/衛浴/房/廳）",
"額外費用_電費？", "額外費用_水費？", "額外費用_瓦斯？", "額外費用_網路？", 
"額外費用_第四台？", "附近有_學校？", "附近有_公園？", "附近有_百貨公司？", 
"附近有_超商？", "附近有_傳統市場？", "附近有_夜市？", "附近有_醫療機構？", 
"附近的捷運站數", "附近的公車站數", "附近的火車站數", "附近的高鐵站數", 
"附近的公共自行車數（實驗中）", "有身份限制？", "有性別限制？", "性別限制", 
"可炊？", "可寵？", "有產權登記？", "刊登者類型", 
anyHeavy("刊登者編碼") "常見刊登者編碼",
"仲介資訊",
"提供家具_床？","提供家具_桌子？","提供家具_椅子？","提供家具_電視？","提供家具_熱水器？",
"提供家具_冷氣？","提供家具_沙發？","提供家具_洗衣機？","提供家具_衣櫃？","提供家具_冰箱？",
"提供家具_網路？","提供家具_第四台？","提供家具_天然瓦斯？"
from file("raw/*.csv") 
where "建築類型" in (0, 1, 2) and "物件類型" in (0, 1, 2, 3, 4) and "建物樓高" < 90
and "所在樓層" < 90 and "坪數" < 500 and "每坪租金（含管理費與停車費）" < 15000
group by "租屋平台", "縣市", "鄉鎮市區", "月租金", 
"押金類型", "押金月數", "押金金額", "需要管理費？", "月管理費", 
"提供車位？", "需要停車費？", "月停車費", "每坪租金（含管理費與停車費）",
"建築類型", "物件類型", "自報頂加？", "所在樓層", "建物樓高", "距頂樓層數",
"坪數", "陽台數", "衛浴數", "房數", "客廳數", "格局編碼（陽台/衛浴/房/廳）",
"額外費用_電費？", "額外費用_水費？", "額外費用_瓦斯？", "額外費用_網路？", 
"額外費用_第四台？", "附近有_學校？", "附近有_公園？", "附近有_百貨公司？", 
"附近有_超商？", "附近有_傳統市場？", "附近有_夜市？", "附近有_醫療機構？", 
"附近的捷運站數", "附近的公車站數", "附近的火車站數", "附近的高鐵站數", 
"附近的公共自行車數（實驗中）", "有身份限制？", "有性別限制？", "性別限制", 
"可炊？", "可寵？", "有產權登記？", "刊登者類型", "仲介資訊",
"提供家具_床？","提供家具_桌子？","提供家具_椅子？","提供家具_電視？","提供家具_熱水器？",
"提供家具_冷氣？","提供家具_沙發？","提供家具_洗衣機？","提供家具_衣櫃？","提供家具_冰箱？",
"提供家具_網路？","提供家具_第四台？","提供家具_天然瓦斯？"
order by "重複物件數" desc
into outfile 'result/deduplicated.csv' format CSVWithNames;

select "租屋平台", count(*) "物件數" from file("result/deduplicated.csv") group by "租屋平台" format Pretty;