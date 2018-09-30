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
        td.pv2.ph3 {{prettyNumber(row.total_count)}}
        td.pv2.ph3(v-for="source in sourceHeaders" :key="source") {{prettyCount(row, source)}}
        td.pv2.ph3
          div.pv1(v-for="file in row.files" :key="file.download_url")
            | [
            a.ttu(:href="file.download_url" target="_blank" rel="noopener")
              | {{file.format || 'csv'}} 
              span.f7.black-50 {{filesize(file.size_byte)}}
            |] 
        td.pv2.ph3
          div(v-if="Array.isArray(row.comment)")
            vue-markdown.ma0.lh-copy(v-for="line in row.comment" :key="line") {{line || '-'}}
          span(v-else) {{row.comment || '-'}}
        

</template>
<script>
import _ from 'lodash'
import filesize from 'filesize'

const RELEASE_STAGE = {
  beta: '本次資料集有新增欄位，但由於資料更新的限制，並非整個月的的物件都有此資料'
}

export default {
  props: {
    rows: {
      type: Array,
      required: true,
      validator (rows) {
        return _.isArray(rows) && rows.every(row => {
          return row.time !== undefined &&
            row.total_count &&
            row.sources &&
            row.files
        })
      }
    },
    idHeader: {
      type: String,
      default: ''
    },
    idFormatter: {
      type: Function,
      default: null
    }
  },
  data () {
    return {}
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
    }
  },
  computed: {
    needIdColumn () {
      return !!this.idHeader
    },
    sourceHeaders () {
      const sources = _.uniq(_.flatten(this.rows.map(
        row => row.sources.map(source => source.name)
      )))
      return sources
    }
  }
}
</script>

