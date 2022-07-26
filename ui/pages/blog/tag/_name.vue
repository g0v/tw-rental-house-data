<template lang="pug">
  main.w-100.mw9-l.pa4.center
    h1.tc
      span.gray 包含
      i.fa.fa-tag.mh2
      | {{tag}}
      span.gray 的貼文
    .tc.gray.f6
      | 其他標籤：
      blog-tag-list.dib(:tags="tags")
    blog-post-list(v-if="posts.length" :posts="posts")
    div(v-else)
      .f3.b.pa3.mt6.tc 這是國王的標籤嗎？ ~"~
      nuxt-link.tc.db(to="/blog") 回部落格首頁
</template>
<script>
import { uniq } from 'lodash'

export default {
  layout: 'blog',
  async asyncData ({ $content, params, redirect }) {
    const targetTag = params.name
    const posts = await $content('blog')
      .only(['slug', 'cover', 'title', 'author', 'created', 'tags', 'excerpt'])
      .where({
        tags: { $contains: targetTag }
      })
      .sortBy('created', 'desc')
      .fetch()

    const allPosts = await $content('blog')
      .only(['tags'])
      .sortBy('created', 'desc')
      .fetch()

    const tags = uniq(allPosts.flatMap(post => post.tags)).filter(tag => tag !== targetTag)

    return { posts, tags }
  },
  computed: {
    tag () {
      return this.$route.params.name
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
