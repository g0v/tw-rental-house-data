<template lang="pug">
  .dc.lh-copy
    .dc__title.fw5 {{dataset.type}}
    .dc__count.mb2.gray.f6 總數： {{dataset.total_count.toLocaleString()}}
    .dc__file(v-for="file in dataset.files" :key="file.format")
      a.ttu(:href="downloadUrl(file)" target="_blank" rel="noopener") [{{file.format}}]
</template>
<script>
import { S3_BASE } from '~/libs/defs'

export default {
  props: {
    dataset: {
      type: Object,
      required: true
    },
    year: {
      type: Number,
      required: true
    },
    period: {
      type: String,
      required: true
    }
  },
  methods: {
    downloadUrl (file) {
      console.warn(file)
      const config = file.download_url
      if (typeof config === 'string') {
        return config
      }
      if (config.isS3) {
        const type = this.dataset.type === '原始資料' ? 'Raw' : 'Deduplicated'
        const format = file.format.toUpperCase()
        const fileName = `[${this.year}${this.period}][${format}][${type}] TW-Rental-Data.zip`
        return `${S3_BASE}${this.year}/${fileName}`
      }
      return ''
    }
  }
}
</script>
<style lang="scss" scoped>
.dc {}
</style>
