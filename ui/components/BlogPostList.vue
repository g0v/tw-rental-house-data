<template lang="pug">
  .flex.flex-wrap.justify-center
    .mw6-l.w-33-l.w-100.fl.relative(v-for="post in posts" :key="post.url")
      article.aspect-ratio--1x1(itemscope itemtype="http://schema.org/Article")
        nuxt-link.pa3.h-100.w-100.dim.no-underline.db.absolute(itemprop="url" :to="`/blog/post/${post.url}/`")
          .post.br2.ba.b--moon-gray.h-100.overflow-hidden
            .post__cover.cover.center.black(:style="{backgroundImage: `url('${post.meta.cover}')`}")
            .pa3
              header.f4.b.black(itemprop="name headline") {{post.meta.title}}
              vue-markdown.f6.black.lh-copy(itemprop="articleBody") {{contentHead(post)}}
            div(itemprop="publisher" itemscope itemtype="https://schema.org/Organization")
              meta(itemprop="name" content="開放台灣民間租屋資料")
            .post__tail
            .post__footer.bt.b--moon-gray.flex.justify-between.light-silver
              .dib.f6(itemprop="author" itemscope itemtype="http://schema.org/Person")
                i.mr2.fa.fa-user-o
                span(itemprop="name") {{post.meta.author}}
              .dib.f6(itemprop="datePublished dateModified" :content="post.meta.created")
                i.mr2.fa.fa-calendar
                | {{contentCreated(post)}}
</template>
<script>
export default {
  props: {
    posts: {
      required: true,
      type: Array
    }
  },
  methods: {
    contentHead (post) {
      return post.content.slice(0, 300)
    },
    contentCreated (post) {
      return new Date(post.meta.created).toLocaleDateString()
    }
  }
}
</script>
<style lang="scss" scoped>
.post {
  &__cover {
    height: 40%;
  }
  &__tail {
    position: absolute;
    bottom: calc(1rem + 1px);
    left: 2rem;
    height: 3.5em;
    margin-top: 1em;
    width: calc(100% - 4rem);
    background: linear-gradient(transparent, white 1.3em);
  }
  &__footer {
    position: absolute;
    bottom: calc(1rem + 1px);
    left: 1rem;
    height: 2em;
    padding: 0.5em;
    width: calc(100% - 2rem);
    overflow: hidden;
  }
}
</style>
