<template lang="pug">
  .annual.ba.b--black.br1.ma4
    .annual__header.flex.justify-between.items-center.bb.b--black.bg-black-30
      h2.ma0.pa2.ml2 {{year}}
      .pa2.mr2
        | 本表格資料下載 [
        a(:download="`${year}.json`" :href="jsonContent") JSON
        | ]
    .annual__seg.seg(v-if="definition.annual.length")
      .seg__title 年度資料
      .seg__table
        DownloadTable(:rows="definition.annual")
    .annual__seg.seg(v-if="definition.quarterly.length")
      .seg__title 每季資料
      .seg__table
        DownloadTable(idHeader="季度", :rows="definition.quarterly")
    .annual__seg.seg
      .seg__title 每月資料
      .seg__table
        DownloadTable(idHeader="月份", :rows="definition.monthly")
</template>
<script>
import DownloadTable from '~/components/DownloadTable'

export default {
  components: {
    DownloadTable
  },
  props: {
    year: {
      type: Number,
      required: true
    },
    // see assets/stats for example
    definition: {
      type: Object,
      required: true
    }
  },
  data() {
    return {}
  },
  computed: {
    jsonContent() {
      return (
        'data:text/plain;charset=utf-8,' +
        encodeURIComponent(JSON.stringify(this.definition, null, 2))
      )
    }
  }
}
</script>
<style lang="scss" scoped>
.seg {
  margin-top: 0.5rem;

  &:not(:last-child) {
    margin-bottom: 2rem;
  }

  > * {
    padding: 0.5rem 1rem;
  }

  &__title {
    font-size: 1.2em;
    border-bottom: 1px solid black;
    border-top: 1px solid black;
  }
}
</style>
