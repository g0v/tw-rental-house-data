<template lang="pug">
  article.w-100.mw8-l.pa4.center(itemscope itemtype="http://schema.org/Article")
    div(v-if="post")
      img.w-100(itemprop="image" v-if="post.cover" :src="post.cover" :alt="post.title")
      h1(itemprop="name headline") {{post.title}}
      .mb3.pb3.bb.b--light-gray
        nuxt-content.lh-copy(itemprop="articleBody" :document="post")
      .flex.flex-wrap.justify-between
        .mb3
          .dib.dark-gray.mr4(itemprop="author" itemscope itemtype="http://schema.org/Person")
            i.mr2.fa.fa-user-o
            span(itemprop="name") {{post.author}}
          .dib.gray(itemprop="datePublished dateModified" :content="post.created")
            i.mr2.fa.fa-calendar
            | {{created}}
        .gray.mb3(v-if="post.tags.length")
          i.mr1.fa.fa-tags
          blog-tag-list.dib(:tags="post.tags")
      div(itemprop="publisher" itemscope itemtype="https://schema.org/Organization")
        meta(itemprop="name" content="開放台灣民間租屋資料")
      twrh-disqus.mw7.center
    div(v-else)
      .f3.b.pa3.mt6.tc 查無此文耶 ~"~
      nuxt-link.tc.db(to="/blog") 回部落格首頁
</template>

<script>
export default {
  layout: 'blog',
  async asyncData ({ $content, params, redirect }) {
    try {
      const post = await $content('blog', params.name)
        .fetch()

      return { post }
    } catch {
      redirect('/blog')
    }
  },
  head () {
    if (this.post) {
      return {
        title: this.post.title,
        meta: [
          {
            hid: 'og:image',
            name: 'og:image',
            content: `https://rentalhouse.g0v.ddio.io${this.post.cover}`
          }
        ]
      }
    }
    return {}
  },
  computed: {
    created () {
      if (this.post) {
        return new Date(this.post.created).toLocaleDateString()
      }
      return ''
    }
  }
}
</script>
<style lang="scss" scoped>
article {
  ::v-deep(.nuxt-content) {
    code {
      font-size: 0.75rem;
      padding: 0.125rem 0.25rem;
      background: #ddd;
      border-radius: 0.125rem;
    }

    li + li {
      margin-top: 0.25rem;
    }

    table {
      border-spacing: 0;
      border: 1px solid #aaa;
      thead th {
        background: #eee;
        padding: 0.25rem 0.5rem;
        text-align: left;
        border-bottom: 1px solid #aaa;
      }
      td {
        border-bottom: 1px solid #aaa;
        padding: 0.25rem 0.5rem;
      }
      tr:last-child td {
        border: none;
      }
    }
  }
}
</style>
