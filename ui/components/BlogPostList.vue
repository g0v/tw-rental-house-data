<template lang="pug">
  .flex.flex-wrap.justify-center
    .mw6-l.w-33-l.w-100.fl.relative(v-for="post in posts" :key="post.url")
      .aspect-ratio--1x1
        nuxt-link.pa3.h-100.w-100.dim.no-underline.db.absolute(:to="`/blog/post/${post.url}`")
          .post.br2.ba.b--moon-gray.h-100.overflow-hidden
            .post__cover.cover.center.black(:style="{backgroundImage: `url('${post.meta.cover}')`}")
            .pa3
              .f4.b.black {{post.meta.title}}
              vue-markdown.f6.black.lh-copy {{contentHead(post)}}
            .post__tail
            .post__footer.bt.b--moon-gray.flex.justify-between.light-silver
              .dib.f6
                i.mr2.fa.fa-user-o
                | {{post.meta.author}}
              .dib.f6
                i.mr2.fa.fa-calendar
                | {{contentCreated(post)}}
</template>
<script>
export default {
  props: {
    posts: {
      requied: true,
      type: Array
    }
  },
  methods: {
    contentHead(post) {
      return post.content.slice(0, 300)
    },
    contentCreated(post) {
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
