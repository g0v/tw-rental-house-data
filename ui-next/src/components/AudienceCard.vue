<template>
  <div class="flex flex-col border border-ink bg-paper">
    <div class="border-b border-ink bg-tile-pale px-4 py-2">
      <h3 class="font-serif text-lg font-bold text-tile-deep">{{ title }}</h3>
    </div>
    <p class="flex-auto px-4 pt-3 text-sm leading-relaxed text-ink-soft">
      {{ description }}
    </p>
    <ul class="px-4 py-3">
      <li v-for="link in links" :key="link.href" class="py-0.5 text-sm">
        <a
          class="text-tile-deep underline underline-offset-2 hover:text-tile"
          :href="link.href"
          :target="link.external ? '_blank' : undefined"
          :rel="link.external ? 'noopener' : undefined"
        >
          {{ link.label }}<span v-if="link.external"> ↗</span>
        </a>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  description: string
  links: { href: string; label: string; external?: boolean }[]
}>()
</script>
