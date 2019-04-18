<template lang="pug">
  main.w-100.mw8-l.pa4.center
    div(v-if="post")
      img.w-100(v-if="post.meta.cover" :src="post.meta.cover" :alt="post.meta.title")
      h1 {{post.meta.title}}
      vue-markdown.mb3.pb3.bb.b--light-gray.lh-copy {{post.content}}
      .flex.flex-wrap.justify-between
        .mb3
          .dib.dark-gray.mr4
            i.mr2.fa.fa-user-o
            | {{post.meta.author}}
          .dib.gray
            i.mr2.fa.fa-calendar
            | {{created}}
        .gray.mb3(v-if="post.meta.tags.length")
          i.mr1.fa.fa-tags
          blog-tag-list.dib(:tags="post.meta.tags")
      disqus.mw7.center
    div(v-else)
      .f3.b.pa3.mt6.tc 查無此文耶 ~"~ 
      nuxt-link.tc.db(to="/blog") 回部落格首頁
</template>

<script>
import { mapState } from 'vuex'
import Disqus from '~/components/Disqus'
import BlogTagList from '@/components/BlogTagList'

export default {
  components: {
    Disqus,
    BlogTagList
  },
  layout: 'blog',
  computed: {
    ...mapState(['blogPosts']),
    post() {
      const postName = this.$route.params.name || ''
      return this.blogPosts.find(thisPost => thisPost.url === postName)
    },
    created() {
      if (this.post) {
        return new Date(this.post.meta.created).toLocaleDateString()
      }
      return ''
    }
  },
  mounted() {
    if (!this.$route.params.name) {
      this.$router.replace('/blog')
    }
  }
}
</script>
