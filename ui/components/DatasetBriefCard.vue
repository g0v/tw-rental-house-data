<template lang="pug">
  .dbc.ba.pa3.b--moon-gray
    h3.mv0.pb3 {{year}} {{period}} {{unit}}
    .dbc__fileList(:class="{'ddc__typeList--single': datasets.length === 1}")
      dataset-card(
        v-for="dataset in datasets"
        :key="dataset.type"
        :dataset="dataset"
        :year="year"
        :period="period"
      )
    .dbc__comment.pt3(v-if="comment")
      vue-markdown.ma0.lh-copy(v-for="line in comment" :key="line") {{line}}
</template>
<script>
export default {
  props: {
    datasets: {
      type: Array,
      required: true,
      validator (val) {
        return Array.isArray(val) && val.every((dataset) => {
          return dataset.type && dataset.total_count && dataset.time && dataset.files
        })
      }
    },
    year: {
      type: Number,
      required: true
    },
    periodPrefix: {
      type: String,
      default: '0'
    },
    unit: {
      type: String,
      default: ''
    }
  },
  computed: {
    period () {
      return this.periodPrefix ? this.datasets[0].time.padStart(2, this.periodPrefix) : ''
    },
    comment () {
      const ret = this.datasets.find(dataset => dataset.comment)
      if (!ret) {
        return ret
      }
      if (Array.isArray(ret.comment)) {
        return ret.comment
      }
      return [ret.comment]
    }
  }
}
</script>
<style lang="scss" scoped>
.dbc {
  &__fileList {
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 1rem;
  }
}
</style>
