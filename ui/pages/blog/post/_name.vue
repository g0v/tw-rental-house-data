<template lang="pug">
  article.w-100.mw8-l.pa4.center(itemscope itemtype="http://schema.org/Article")
    div(v-if="post")
      img.w-100(itemprop="image" v-if="post.meta.cover" :src="post.meta.cover" :alt="post.meta.title")
      h1(itemprop="name headline") {{post.meta.title}}
      .mb3.pb3.bb.b--light-gray.lh-copy(itemprop="articleBody" v-html="post.html")
      .flex.flex-wrap.justify-between
        .mb3
          .dib.dark-gray.mr4(itemprop="author" itemscope itemtype="http://schema.org/Person")
            i.mr2.fa.fa-user-o
            span(itemprop="name") {{post.meta.author}}
          .dib.gray(itemprop="datePublished dateModified" :content="this.post.meta.created")
            i.mr2.fa.fa-calendar
            | {{created}}
        .gray.mb3(v-if="post.meta.tags.length")
          i.mr1.fa.fa-tags
          blog-tag-list.dib(:tags="post.meta.tags")
        div(itemprop="publisher" itemscope itemtype="https://schema.org/Organization")
          meta(itemprop="name" content="開放台灣民間租屋資料")
      disqus.mw7.center
    div(v-else)
      .f3.b.pa3.mt6.tc 查無此文耶 ~"~ 
      nuxt-link.tc.db(to="/blog") 回部落格首頁
</template>

<script>
import { mapState } from 'vuex'
import markdownIt from 'markdown-it'
import Disqus from '~/components/Disqus'
import BlogTagList from '@/components/BlogTagList'

const md = markdownIt()

export default {
  components: {
    Disqus,
    BlogTagList
  },
  layout: 'blog',
  head() {
    if (this.post) {
      return {
        title: this.post.meta.title,
        meta: [
          {
            hid: 'og:image',
            name: 'og:image',
            content: `https://rentalhouse.g0v.ddio.io${this.post.meta.cover}`
          }
        ]
      }
    }
    return {}
  },
  computed: {
    ...mapState(['blogPosts']),
    post() {
      const postName = this.$route.params.name || ''
      const target = this.blogPosts.find(thisPost => thisPost.url === postName)
      if (target && !target.html) {
        target.html = md.render(target.content)
      }
      return target
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
