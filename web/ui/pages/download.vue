<template lang="pug">
  main.w-100.mw9.center.pa4
    article.mw7.center.lh-copy
      p.mv2
      | 「開放民間租屋資料」希望提供對租屋議題有興趣的單位，一份長期、開放，而且詳細的租屋資料集，
      | 去除有著作權與隱私疑慮的資料後，以 
      a(href='https://creativecommons.org/publicdomain/zero/1.0/deed.zh_TW') CC0
      |  釋出，為台灣的租賃市場與居住議題建立研究的基礎資料。
      p.mv3
      | 本資料集的來源目前為 
      a(href='https://rent.591.com.tw/') 591 租屋網
      | ，預計每月、每季、每年都會發佈一份該期間內曾經出現過的所有出租物件，
      | 除了資料正規化外，不做額外的資料處理與刪減，希望盡量保持資料的原始狀態。
      | 後續也會持續擴充資料來源至各大租屋網與其他代管業者的公開資訊。
      p.mv3
      | 本資料集是以現狀提供，並在相關法律容許的最大範圍內，主張免除提供者所有的擔保責任，
      | 包括但不限於合用性、正確性、權利瑕疵等，倘若資料的使用引發後續使用者的情緒困擾，
      | 或過於沉迷肇生
      a(href='https://duckduckgo.com/?q=多元成家三法') 多元成家
      | 、
      a(href='https://duckduckgo.com/?q=毀家廢婚') 毀家廢婚
      | 、或
      a(href='https://duckduckgo.com/?q=一男一女一夫一妻一生一世') 一男一女一夫一妻一生一世
      | ，使用者須為其後個案使用情境造成的結果自負其責，不得歸咎於提供者。
      p.mv3
      | 關於資料集的欄位與編碼表，請見「
      nuxt-link(to="/about-data-set") 關於資料集
      | 」。
      br
      | 如果好奇本專案的規劃、想要參與，或是發現問題，請至 
      a(href='https://github.com/g0v/tw-rental-house-data') Github
      |  開票。
      br
      | 若你是資料擁有者，而且認為本資料集有侵犯隱私或其他疑慮的，歡迎
      a(href="mailto:open-tw-rental-house@ddio.io") 來信
      | 要求移除。
</template>
<script>
export default {
}
</script>

