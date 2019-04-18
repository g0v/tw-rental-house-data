<template lang="pug">
  .tags
    nuxt-link.tag.mr1.dim.no-underline.outline-0(
      v-for="tag in tagTexts"
      :key="tag"
      :to="`/blog/tag/${tag}`"
    ) {{tag}}
</template>
<script>
export default {
  props: {
    tags: {
      required: true,
      type: Array
    }
  },
  computed: {
    tagTexts() {
      return this.tags.map(tag => {
        if (typeof tag === 'string') {
          return tag
        } else if (tag.name) {
          return tag.name
        }
        return tag.toString()
      })
    }
  }
}
</script>
<style lang="scss" scoped>
.tag:not(:last-child):after {
  content: '-';
  margin-left: 0.25rem;
}
</style>
