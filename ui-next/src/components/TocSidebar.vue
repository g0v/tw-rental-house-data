<template>
  <nav
    class="sticky top-8 hidden max-h-[calc(100vh-4rem)] w-60 shrink-0 self-start overflow-y-auto pt-10 xl:block"
    aria-label="目次"
  >
    <h2 class="font-serif text-lg font-bold">目次</h2>
    <ul class="mt-2 border-l border-rule text-sm leading-relaxed">
      <li v-for="heading in headings" :key="heading.slug">
        <a
          class="block py-0.5 text-ink-soft hover:text-tile-deep hover:underline"
          :class="heading.depth <= 2 ? 'pl-3' : 'pl-7'"
          :href="`#${heading.slug}`"
          >{{ heading.text }}</a
        >
      </li>
    </ul>
  </nav>
</template>

<script setup lang="ts">
defineProps<{
  headings: { depth: number; slug: string; text: string }[]
}>()
</script>
