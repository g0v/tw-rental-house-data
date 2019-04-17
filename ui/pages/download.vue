<template lang="pug">
  section.w-100.mw9.center.pa4
    div.mw7.center.lh-copy
      h1 打包回家玩～
      AboutDataBrief
      p.mv3
        | 關於資料集的欄位與編碼表，請見「
        nuxt-link(to="/about-data-set") 關於資料集
        | 」。
        br
        | 如果好奇本專案的規劃、想要參與，或是發現問題，請至 
        a(href='https://github.com/g0v/tw-rental-house-data' target="_blank" rel="noopener") Github
        |  開票。
        br
        | 若你是資料擁有者，而且認為本資料集有侵犯隱私或其他疑慮的，歡迎
        a(href="mailto:open-tw-rental-house@ddio.io") 來信
        | 要求移除。

    main.w-100(v-for="year in years" :key="year.year")
      AnnualDownload(:year="year.year" :definition="year.data")
    
    Disqus.mw7.center
</template>
<script>
import AnnualDownload from '~/components/AnnualDownload'
import AboutDataBrief from '~/components/AboutDataBrief'
import Disqus from '~/components/Disqus'

import def2018 from '~/assets/stats/2018.json'
import def2019 from '~/assets/stats/2019.json'

export default {
  components: {
    AnnualDownload,
    AboutDataBrief,
    Disqus
  },
  head () {
    return {
      title: '打包回家玩',
      meta: [
        { hid: 'og:image', name: 'og:image', content: 'https://rentalhouse.g0v.ddio.io/imgs/download-og.png' }
      ]
    }
  },
  data () {
    return {
      years: [
        { year: 2019, data: def2019 },
        { year: 2018, data: def2018 }
      ]
    }
  }
}
</script>
