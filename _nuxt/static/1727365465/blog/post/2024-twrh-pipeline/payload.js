__NUXT_JSONP__("/blog/post/2024-twrh-pipeline", (function(a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,A,B,C,D){return {data:[{post:{slug:"2024-twrh-pipeline",description:"寫出網路爬蟲，是一回事，但要能夠長期維運，並將它轉換為資料集，則完全是另一項工作。這篇文章將介紹我們如何處理開放台灣租屋資料（以下簡稱開租）的流程。\n開租總共使用三組流程，並將中繼、最終資料，存在三種資料表中。",title:"開放台灣租屋資料處理流程",author:"ddio",created:"2024-03-10T00:00:00.000Z",cover:"\u002Fimgs\u002Fblog\u002Fpipeline-2024.jpeg",tags:["關於","技術文件"],toc:[{id:q,depth:f,text:r},{id:s,depth:f,text:t},{id:u,depth:f,text:v},{id:w,depth:f,text:x}],body:{type:y,children:[{type:b,tag:e,props:{},children:[{type:a,value:z}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:A}]},{type:a,value:c},{type:a,value:c},{type:b,tag:g,props:{id:q},children:[{type:b,tag:h,props:{href:"#%E6%AF%8F%E6%97%A5%E4%BE%8B%E8%A1%8C%E5%B7%A5%E4%BD%9C---%E5%84%B2%E5%AD%98%E5%89%8D%E6%97%A5%E6%89%80%E6%9C%89%E7%A7%9F%E5%B1%8B%E5%B9%B3%E5%8F%B0%E7%9A%84%E7%89%A9%E4%BB%B6%E6%9C%80%E6%96%B0%E8%B3%87%E8%A8%8A",ariaHidden:i,tabIndex:j},children:[{type:b,tag:k,props:{className:[l,m]},children:[]}]},{type:a,value:r}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:b,tag:n,props:{alt:"每日例行工作",src:"\u002Fimgs\u002Fblog\u002Ftwrh-daily-pipeline.png"},children:[]}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:"這是開租的核心工作，每日清晨，系統自動甦醒後，會以各租屋平台為單位"}]},{type:a,value:c},{type:b,tag:o,props:{},children:[{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"載入該平台設定"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"擷取平台的物件清單，若有除了 ID 以外的資訊，則會一併儲存在未正規劃的資料表中，以盡量保留原始資料"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"根據當日新增的清單，再合併資料庫中尚未標示為關閉的物件，逐一擷取物件的詳細資訊，並儲存至未正規化的資料表中"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"將未正規化的資料表，轉換為正規化的資料表，並分別儲存至\n"},{type:b,tag:o,props:{},children:[{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"每日歷史表，以供物件狀態等，需要多日資料才能判讀資訊分析"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"物件總覽表，供後續長天期分析"}]},{type:a,value:c}]},{type:a,value:c}]},{type:a,value:c}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:"附帶一題，雖然系統架構上，開租支援多租屋平台資料紀錄，但由於缺乏開發資源，截至 2024 年三月為止，僅有 591 租屋網，是有完整執行的。"}]},{type:a,value:c},{type:b,tag:g,props:{id:s},children:[{type:b,tag:h,props:{href:"#%E4%B8%89%E7%A8%AE%E8%B3%87%E6%96%99%E8%A1%A8---%E6%98%AF%E5%90%A6%E6%AD%A3%E8%A6%8F%E5%8A%83-x-%E6%AF%8F%E6%97%A5%E6%88%96%E6%9C%80%E6%96%B0%E7%B8%BD%E8%A6%BD",ariaHidden:i,tabIndex:j},children:[{type:b,tag:k,props:{className:[l,m]},children:[]}]},{type:a,value:t}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:b,tag:n,props:{alt:"資料表圖例",src:"\u002Fimgs\u002Fblog\u002Ftwrh-table-types.png"},children:[]}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:"由每日例行工作可知，開租的資料表分為三種，並用兩項屬性來區分："}]},{type:a,value:c},{type:b,tag:o,props:{},children:[{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"是否正規化\n"},{type:b,tag:B,props:{},children:[{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"由於開租希望能夠彙整多個平台的資訊，因此會將各平台的資料，轉為統一個資料格式，方便讓使用者進行資料分析"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"但正規劃的過程中，必定會刪除、修改部份資訊，因此我們也會保留原始資料，若將來"},{type:b,tag:C,props:{to:"\u002Fabout-data-set\u002F"},children:[{type:a,value:"資料集格式"}]},{type:a,value:"調整時，也能使用原始資料（未正歸化資料），更新資料集"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"由於未正規化資料表，可能包含不適合公開的資訊，例如詳細的地址，因此並不會提供給外界使用"}]},{type:a,value:c}]},{type:a,value:c}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"每日留存，或是僅保留最新資訊\n"},{type:b,tag:B,props:{},children:[{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"資料庫中，會以日期為單位，儲存最近 60 天的資料，以判斷物件的狀態，例如是否已出租，並作為事後疑難排解的依據"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:a,value:"但由於開租的目的是提供長期資料分析，因此也會將每日的資料，轉換為最新總覽，每個物件僅保留最後的資料，以供使用者進行資料分析"}]},{type:a,value:c}]},{type:a,value:c}]},{type:a,value:c}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:"由這兩個屬性，我們可以得到三種資料表："}]},{type:a,value:c},{type:b,tag:o,props:{},children:[{type:a,value:c},{type:b,tag:d,props:{},children:[{type:b,tag:p,props:{},children:[{type:a,value:"未正規化的最新總覽"}]},{type:a,value:"，僅供內部流程暫存、分析、資料復原使用"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:b,tag:p,props:{},children:[{type:a,value:"正規化的每日歷史資訊"}]},{type:a,value:" ，僅供內部流程暫存、分析、資料復原使用"}]},{type:a,value:c},{type:b,tag:d,props:{},children:[{type:b,tag:p,props:{},children:[{type:a,value:"正規化的最新總覽"}]},{type:a,value:"，也是開租釋出的"},{type:b,tag:C,props:{to:"\u002Fdownload\u002F"},children:[{type:a,value:"資料集"}]}]},{type:a,value:c}]},{type:a,value:c},{type:b,tag:g,props:{id:u},children:[{type:b,tag:h,props:{href:"#%E6%AF%8F%E6%9C%88%E4%BE%8B%E8%A1%8C%E5%B7%A5%E4%BD%9C---%E6%95%B4%E4%BD%B5%E7%95%B6%E6%9C%88%E6%89%80%E6%9C%89%E7%A7%9F%E5%B1%8B%E5%B9%B3%E5%8F%B0%E7%9A%84%E7%89%A9%E4%BB%B6%E8%B3%87%E8%A8%8A",ariaHidden:i,tabIndex:j},children:[{type:b,tag:k,props:{className:[l,m]},children:[]}]},{type:a,value:v}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:b,tag:n,props:{alt:"每月例行工作",src:"\u002Fimgs\u002Fblog\u002Ftwrh-monthly-pipeline.png"},children:[]}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:"每月例行工作，是為了將每日例行工作的資料，整併成一個月的資料，並將其轉換為最新總覽，以供使用者進行資料分析。"}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:"為了節省資料庫計算資源，每月例行工作，僅使用資料庫匯出原始資料，後續則使用 ClickHouse ，製作消除重複住宅資料集。"}]},{type:a,value:c},{type:b,tag:g,props:{id:w},children:[{type:b,tag:h,props:{href:"#%E6%AF%8F%E5%AD%A3%E5%B9%B4%E7%9A%84%E4%BE%8B%E8%A1%8C%E5%B7%A5%E4%BD%9C---%E6%95%B4%E4%BD%B5%E7%95%B6%E5%AD%A3%E5%B9%B4%E6%89%80%E6%9C%89%E7%A7%9F%E5%B1%8B%E5%B9%B3%E5%8F%B0%E7%9A%84%E7%89%A9%E4%BB%B6%E8%B3%87%E8%A8%8A",ariaHidden:i,tabIndex:j},children:[{type:b,tag:k,props:{className:[l,m]},children:[]}]},{type:a,value:x}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:b,tag:n,props:{alt:"每季、年例行工作",src:"\u002Fimgs\u002Fblog\u002Ftwrh-quarterly-pipeline.png"},children:[]}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:"由於每季、年的資料量過大，從原始資料開始，我們就會使用 ClickHouse 進行資料整併，並將其轉換為最新總覽、消除重複住宅資料集，以供使用者進行資料分析。"}]}]},excerpt:{type:y,children:[{type:b,tag:e,props:{},children:[{type:a,value:z}]},{type:a,value:c},{type:b,tag:e,props:{},children:[{type:a,value:A}]}]},dir:"\u002Fblog",path:"\u002Fblog\u002F2024-twrh-pipeline",extension:".md",createdAt:D,updatedAt:D}}],fetch:{},mutations:void 0}}("text","element","\n","li","p",2,"h2","a","true",-1,"span","icon","icon-link","img","ol","strong","每日例行工作---儲存前日所有租屋平台的物件最新資訊","每日例行工作 - 儲存前日所有租屋平台的物件最新資訊","三種資料表---是否正規劃-x-每日或最新總覽","三種資料表 - 是否正規劃 x 每日或最新總覽","每月例行工作---整併當月所有租屋平台的物件資訊","每月例行工作 - 整併當月所有租屋平台的物件資訊","每季年的例行工作---整併當季年所有租屋平台的物件資訊","每季、年的例行工作 - 整併當季、年所有租屋平台的物件資訊","root","寫出網路爬蟲，是一回事，但要能夠長期維運，並將它轉換為資料集，則完全是另一項工作。這篇文章將介紹我們如何處理開放台灣租屋資料（以下簡稱開租）的流程。","開租總共使用三組流程，並將中繼、最終資料，存在三種資料表中。","ul","nuxt-link","2024-09-26T15:43:42.056Z")));