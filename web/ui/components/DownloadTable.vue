<template lang="pug">
  table.download.ba.b--black-20.w-100.collapse
    tbody
      tr.striped--light-gray
        th.pv2.ph3.tl.f6.fw6(v-if="needIdColumn") {{idHeader}}
        th.pv2.ph3.tl.f6.fw6 總物件數
        th.pv2.ph3.tl.f6.fw6(v-for="source in sourceHeaders" :key="source") {{source}} 物件數
        th.pv2.ph3.tl.f6.fw6 檔案解壓縮後大小
        th.pv2.ph3.tl.f6.fw6 附註
        th.pv2.ph3.tl.f6.fw6 下載連結
      tr.striped--light-gray(v-for="row in rows" :key="row.id")
        td.pv2.ph3(v-if="needIdColumn") {{idName(row.id)}}
        td.pv2.ph3 {{prettyNumber(row.total_count)}}
        td.pv2.ph3(v-for="source in sourceHeaders" :key="source") {{prettyCount(row, source)}}
        td.pv2.ph3 {{filesize(row.file_size_byte)}}
        td.pv2.ph3 {{row.comment || '-'}}
        td.pv2.ph3
          | [
          a(:href="row.download_url" target="_blank" rel="noopener") CSV
          | ]

</template>
<script>
import _ from 'lodash'
import filesize from 'filesize'

export default {
  props: {
    rows: {
      type: Array,
      required: true,
      validator (rows) {
        return _.isArray(rows) && rows.every(row => {
          return row.id !== undefined &&
            row.total_count &&
            row.sources &&
            row.file_size_byte &&
            row.download_url
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
      if (this.idFormatter && typeof a === 'function') {
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

