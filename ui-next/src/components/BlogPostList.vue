<template>
  <div class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
    <article
      v-for="post in posts"
      :key="post.id"
      class="flex flex-col border border-rule bg-paper transition-colors hover:border-tile"
      itemscope
      itemtype="http://schema.org/Article"
    >
      <a
        class="flex h-full flex-col"
        itemprop="url"
        :href="`/blog/post/${post.id}/`"
      >
        <div class="relative aspect-video overflow-hidden border-b border-rule">
          <img
            class="absolute inset-0 h-full w-full scale-110 object-cover blur-lg"
            aria-hidden="true"
            alt=""
            :src="post.cover.placeholder"
          />
          <img
            class="lqip relative h-full w-full object-cover"
            itemprop="image"
            :src="post.cover.src"
            :srcset="post.cover.srcset"
            :sizes="post.cover.sizes"
            :width="post.cover.width"
            :height="post.cover.height"
            :alt="post.title"
            loading="lazy"
            decoding="async"
            onload="this.classList.add('is-loaded')"
          />
        </div>
        <div class="flex-auto px-4 pt-3">
          <h2
            class="font-serif text-lg font-bold text-ink"
            itemprop="name headline"
          >
            {{ post.title }}
          </h2>
          <p class="mt-2 line-clamp-4 text-sm leading-relaxed text-ink-soft">
            {{ post.excerpt }}
          </p>
        </div>
        <div
          class="mt-3 flex justify-between border-t border-rule px-4 py-2 text-xs text-ink-soft"
        >
          <span itemprop="author" itemscope itemtype="http://schema.org/Person"
            ><span itemprop="name">{{ post.author }}</span></span
          >
          <time
            itemprop="datePublished dateModified"
            :datetime="post.createdIso"
            class="font-mono"
            >{{ post.createdLabel }}</time
          >
        </div>
        <span
          itemprop="publisher"
          itemscope
          itemtype="https://schema.org/Organization"
        >
          <meta itemprop="name" content="開放台灣民間租屋資料" />
        </span>
      </a>
    </article>
  </div>
</template>

<script setup lang="ts">
import type { CardCover } from '../lib/blog'

export interface BlogPostCard {
  id: string
  title: string
  author: string
  /** build 時由 astro:assets 產好的 srcset，見 lib/blog.ts toCard */
  cover: CardCover
  excerpt: string
  createdIso: string
  createdLabel: string
}

defineProps<{ posts: BlogPostCard[] }>()
</script>
