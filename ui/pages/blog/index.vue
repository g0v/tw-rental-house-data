<template lang="pug">
  main.w-100.mw9-l.pa4.center
    h1.tc 關於爬蟲錯誤說明、專案開發、衍生應用
    .tc.gray.f6
      i.fa.fa-tags.mr1
      blog-tag-list.dib(:tags="tags")
    blog-post-list(:posts="posts")
</template>
<script>
import { uniq } from 'lodash'

export default {
  layout: 'blog',
  async asyncData ({ $content, params, redirect }) {
    const posts = await $content('blog')
      .only(['slug', 'cover', 'title', 'author', 'created', 'tags', 'excerpt'])
      .sortBy('created', 'desc')
      .fetch()

    const tags = uniq(posts.flatMap(post => post.tags))

    return { posts, tags }
  },
  head () {
    return {
      title: '部落格'
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
