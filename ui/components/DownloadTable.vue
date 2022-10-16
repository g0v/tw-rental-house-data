<template lang="pug">
  table.download.ba.b--black-20.w-100.collapse
    tbody
      tr.striped--light-gray
        th.pv2.ph3.tl.f6.fw6(v-if="needIdColumn") {{idHeader}}
        th.pv2.ph3.tl.f6.fw6 內容
        th.pv2.ph3.tl.f6.fw6 資料集版本
        th.pv2.ph3.tl.f6.fw6 總物件數
        th.pv2.ph3.tl.f6.fw6(v-for="source in sourceHeaders" :key="source") {{source}} 物件數
        th.pv2.ph3.tl.f6.fw6 下載連結 / 解壓縮後大小
        th.pv2.ph3.tl.f6.fw6 附註
      tr.striped--light-gray(v-for="row in rows" :key="row.time + row.type")
        td.pv2.ph3(v-if="needIdColumn") {{idName(row.time)}}
        td.pv2.ph3 {{row.type}}
        td.pv2.ph3
          nuxt-link(:to="dataUrl(row.data_ver)")
            span.ttu(:title="dataDesp(row.data_ver)") {{row.data_ver}}
        td.pv2.ph3 {{prettyTotal(row)}}
        td.pv2.ph3(v-for="source in sourceHeaders" :key="source") {{prettyCount(row, source)}}
        td.pv2.ph3
          div.pv1(v-for="file in row.files" :key="file.format")
            | [
            a.ttu(:href="downloadUrl(file, row)" target="_blank" rel="noopener")
              | {{file.format || 'csv'}}
              span.f7.black-50 {{filesize(file.size_byte)}}
            |]
        td.pv2.ph3
          div(v-if="Array.isArray(row.comment)")
            vue-markdown.ma0.lh-copy(v-for="line in row.comment" :key="line") {{line || '--'}}
          vue-markdown(v-else) {{row.comment || '--'}}
</template>
<script>
import _ from 'lodash'
import filesize from 'filesize'
import { S3_BASE } from '~/libs/defs'

const RELEASE_STAGE = {
  beta:
    '本次資料集有新增欄位，但由於資料更新的限制，並非整個月的的物件都有此資料'
}

export default {
  props: {
    year: {
      type: Number,
      required: true
    },
    rows: {
      type: Array,
      required: true,
      validator (rows) {
        return (
          _.isArray(rows) &&
          rows.every((row) => {
            return row.time !== undefined && row.sources && row.files
          })
        )
      }
    },
    idHeader: {
      type: String,
      default: ''
    },
    idFormatter: {
      type: Function,
      default: null
    },
    periodPrefix: {
      type: String,
      default: '0'
    }
  },
  data () {
    return {}
  },
  computed: {
    needIdColumn () {
      return !!this.idHeader
    },
    sourceHeaders () {
      const sources = _.uniq(
        _.flatten(this.rows.map(row => row.sources.map(source => source.name)))
      )
      return sources
    }
  },
  methods: {
    idName (id) {
      if (this.idFormatter) {
        return this.idFormatter(id)
      } else {
        return id
      }
    },
    prettyNumber (number) {
      return number.toLocaleString()
    },
    prettyTotal (row) {
      let total = 0
      if (row.total_count) {
        total = row.total_count
      } else {
        row.sources.forEach((source) => {
          total += source.count
        })
      }
      return this.prettyNumber(total)
    },
    prettyCount (row, sourceName) {
      const source = row.sources.find(source => source.name === sourceName)
      if (source) {
        return this.prettyNumber(source.count)
      } else {
        return '-'
      }
    },
    filesize (size) {
      return filesize(size)
    },
    dataUrl (dataVer) {
      const versionTokens = dataVer.split(' ')
      return `/about-data-set/${versionTokens[0]}`
    },
    dataDesp (dataVer) {
      const versionTokens = dataVer.split(' ')
      if (versionTokens.length > 1) {
        return RELEASE_STAGE[versionTokens[1].toLowerCase()]
      }
      return ''
    },
    downloadUrl (file, row) {
      const config = file.download_url
      if (typeof config === 'string') {
        return config
      }
      if (config.isS3) {
        const period = this.periodPrefix ? row.time.padStart(2, this.periodPrefix) : ''
        const type = row.type === '原始資料' ? 'Raw' : 'Deduplicated'
        const format = file.format.toUpperCase()
        const fileName = `[${this.year}${period}][${format}][${type}] TW-Rental-Data.zip`
        return `${S3_BASE}${this.year}/${fileName}`
      }
      return ''
    }
  }
}
</script>
