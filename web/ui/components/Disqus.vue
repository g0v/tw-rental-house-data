<template lang="pug">
  vue-disqus.w-100.mt5(shortname="tw-rental-house-data" :identifier="$route.fullPath" :url="url")
</template>
<script>
export default {
  data () {
    return {}
  },
  computed: {
    url () {
      if (!process.browser) {
        return ''
      }
      const host = window.location.origin
      return host + '/' + this.$route.fullPath
    }
  }
}
</script>
