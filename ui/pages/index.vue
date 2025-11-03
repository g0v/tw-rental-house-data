<template lang="pug">
  main.index
    .mw7.center.pv4.pt5-l.pb6-l.ph3
      h1 開放台灣民間租屋資料
      about-data-brief
    .index__recentPosts.pv4.pv6-l.ph3
      .mw8.center
        h2.mt0.mb4 近期公告
        .index__postList
          nuxt-link.post.flex.flex-column-reverse.flex-row-l.items-center.black.dim(
            v-for="post in recentPosts"
            :key="post.slug"
            :to="`/blog/post/${post.slug}/`"
          )
            .flex-auto.flex.flex-column.mt3.mr4-l.mt0-l
              h3.mv0.f4 {{post.title}}
              nuxt-content.lh-copy(:document="{ body: removeHref(post.excerpt) }")
              span.tr.f6.gray
                span.underline.mr1 閱讀更多
                span ➡️
            .post__cover.flex-none
              .aspect-ratio.aspect-ratio--16x9
                img.aspect-ratio--object(:Src="post.cover" :alt="post.title")
    .mw8.center.pv4.pv6-l.ph3
      h2.mt0.mb4 最新資料集
      .index__datasetList
        dataset-brief-card(
          :year="lastAnnualData.year"
          period-prefix=""
          unit="年"
          :datasets="lastAnnualData.datasets"
        )
        dataset-brief-card(
          :year="lastQuarterlyData.year"
          period-prefix="Q"
          unit=""
          :datasets="lastQuarterlyData.datasets"
        )
        dataset-brief-card(
          :year="lastMonthlyData.year"
          period-prefix="0"
          unit="月"
          :datasets="lastMonthlyData.datasets"
        )
      .mt3.tr
        nuxt-link.pa3(to="/download") 查看所有資料集 ➡️
    twrh-disqus.mw7.center
</template>
<script>
import lastYear from '~/assets/stats/2023.json'
import thisYear from '~/assets/stats/2025.json'

export default {
  async asyncData ({ $content }) {
    const posts = await $content('blog')
      .only(['slug', 'cover', 'title', 'created', 'excerpt'])
      .sortBy('created', 'desc')
      .limit(3)
      .fetch()

    return { recentPosts: posts }
  },
  computed: {
    lastAnnualData () {
      return this.getLastDatasetTuple('annual')
    },
    lastQuarterlyData () {
      return this.getLastDatasetTuple('quarterly')
    },
    lastMonthlyData () {
      return this.getLastDatasetTuple('monthly')
    }
  },
  methods: {
    getLastDatasetTuple (category) {
      if (thisYear[category] && thisYear[category].length >= 2) {
        return {
          year: thisYear.year,
          datasets: thisYear[category].slice(-2)
        }
      }
      return {
        year: lastYear.year,
        datasets: lastYear[category].slice(-2)
      }
    },
    removeHref (post) {
      // except somehow get unclosed href tag, remove it as workaround
      if (post.type === 'text' || !post.children) {
        return post
      }
      const children = post.children.map((item) => {
        if (item.type === 'element' && item.tag === 'a') {
          return {
            ...item,
            tag: 'span'
          }
        }
        return this.removeHref(item)
      })
      return {
        ...post,
        children
      }
    }
  }
}
</script>
<style lang="scss" scoped>
.index {
  h1, h2, h3 {
    font-weight: 600;
  }
  &__recentPosts {
    background: $green-100;
  }

  &__datasetList {
    > div:not(:first-child) {
      margin-top: 1rem;
    }
    @include large-screen {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      column-gap: 1rem;
      > div:not(:first-child) {
        margin: 0;
      }
    }
  }
}

.post {
  text-decoration: none;
  margin-top: 3rem;
  &__cover {
    width: 100%;
    img {
      object-fit: cover;
    }

    @include large-screen {
      width: 25%;
    }
  }
  @include large-screen {
    &:first-child {
      grid-column: 1 / span 2;
    }
  }
}
</style>
