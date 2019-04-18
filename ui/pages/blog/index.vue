<template lang="pug">
  main.w-100.mw9-l.pa4.center
    p.tc 關於爬蟲錯誤說明、專案開發、衍生應用
    .tc.gray.f6
      i.fa.fa-tags.mr1
      blog-tag-list.dib(:tags="tags")
    blog-post-list(:posts="blogPosts")
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
  head() {
    return {
      title: '部落格'
    }
  },
  computed: {
    ...mapState(['blogPosts']),
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
      return Object.keys(counter).map(tag => {
        return {
          name: tag,
          count: counter[tag]
        }
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
