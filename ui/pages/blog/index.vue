<template lang="pug">
  main.w-100.mw9-l.pa4.center
    p.tc 關於爬蟲錯誤說明、專案開發、衍生應用
    .flex.flex-wrap
      .pa3.w-50-l.w-100(v-for="post in blogPosts" :key="post.url")
        .post.br2.ba.b--moon-gray.pa3.relative.overflow-hidden
          nuxt-link.db.f4.b.dim.no-underline.black(:to="`/blog/post/${post.url}`") {{post.meta.title}}
          .f6(v-html="post.content")
          .post__cover
</template>
<script>
import { mapState } from 'vuex'

export default {
  layout: 'blog',
  computed: {
    ...mapState(['blogPosts'])
  }
}
</script>
<style lang="scss" scoped>
.post {
  height: 10em;

  &__cover {
    position: absolute;
    bottom: 0;
    left: 0;
    height: 2em;
    width: 100%;
    background: linear-gradient(transparent, white 67%, white);
  }
}
</style>
