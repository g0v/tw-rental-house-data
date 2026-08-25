<template>
  <span class="inline-flex flex-wrap gap-x-2 gap-y-1">
    <a
      v-for="tag in tags"
      :key="tag"
      class="text-tile-deep underline decoration-rule underline-offset-2 hover:decoration-tile"
      :href="`/blog/tag/${tag}/`"
      >{{ tag }}</a
    >
  </span>
</template>

<script setup lang="ts">
defineProps<{ tags: string[] }>()
</script>
