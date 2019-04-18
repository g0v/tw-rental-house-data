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
import { mapState } from 'vuex'
import BlogPostList from '@/components/BlogPostList'
import BlogTagList from '@/components/BlogTagList'

export default {
  components: {
    BlogPostList,
    BlogTagList
  },
  layout: 'blog',
  computed: {
    ...mapState(['blogPosts']),
    tag() {
      return this.$route.params.name
    },
    posts() {
      return this.blogPosts.filter(post => post.meta.tags.includes(this.tag))
    },
    tags() {
      const counter = {}
      this.blogPosts.forEach(post => {
        post.meta.tags.forEach(tag => {
          if (!counter[tag]) {
            counter[tag] = 0
          }
          counter[tag] += 1
        })
      })
      return Object.keys(counter)
        .map(tag => {
          return {
            name: tag,
            count: counter[tag]
          }
        })
        .filter(tag => tag.name !== this.tag)
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
