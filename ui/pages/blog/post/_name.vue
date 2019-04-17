<template lang="pug">
  main.w-100.mw9-l.pa4.center(v-if="post")
    h1 {{post.meta.title}}
    div(v-html="post.content")
</template>

<script>
import { mapState } from 'vuex'

export default {
  layout: 'blog',
  computed: {
    ...mapState(['blogPosts']),
    post() {
      const postName = this.$route.params.name || ''
      return this.blogPosts.find(thisPost => thisPost.url === postName)
    }
  },
  created() {
    if (!this.$route.params.name) {
      this.$router.replace('/blog')
    }
  }
}
</script>
