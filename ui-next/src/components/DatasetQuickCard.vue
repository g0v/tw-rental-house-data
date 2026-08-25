<template>
  <div class="flex flex-col border-2 border-ink bg-paper">
    <div
      class="flex flex-wrap items-baseline justify-between gap-x-4 border-b-2 border-ink bg-tile px-4 py-2 text-paper"
    >
      <h3 class="font-serif text-lg font-bold">{{ heading }}</h3>
      <span class="font-mono text-sm">本期資料 No. {{ issueNumber }}</span>
    </div>
    <div class="grid flex-auto gap-4 px-4 py-4 sm:grid-cols-2">
      <div v-for="row in rows" :key="row.type">
        <div class="font-medium">{{ row.type }}</div>
        <div class="mt-1 text-sm text-ink-soft">
          總物件數
          <span class="font-mono">{{ row.total_count.toLocaleString() }}</span>
        </div>
        <ul class="mt-2">
          <li v-for="file in row.files" :key="file.format ?? 'csv'" class="py-0.5">
            <a
              class="font-mono text-sm text-tile-deep underline uppercase"
              :href="fileUrl(file, row)"
              target="_blank"
              rel="noopener"
              >{{ file.format ?? 'csv' }} ZIP</a
            >
            <span class="ml-2 font-mono text-xs text-ink-soft">{{
              prettyFilesize(file.size_byte)
            }}</span>
          </li>
        </ul>
      </div>
    </div>
    <div
      v-if="comments.length"
      class="border-t border-rule px-4 py-2 text-sm leading-relaxed text-ink-soft"
    >
      <!-- eslint-disable-next-line vue/no-v-html — renderCommentHtml escapes everything but links -->
      <p v-for="line in comments" :key="line" v-html="renderCommentHtml(line)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DatasetFile, DatasetRow } from '../data/stats'
import {
  commentLines,
  downloadUrl,
  periodLabel,
  prettyFilesize,
  renderCommentHtml,
  type PeriodPrefix
} from '../lib/download'

const props = defineProps<{
  heading: string
  year: number
  prefix: PeriodPrefix
  rows: DatasetRow[]
}>()

const issueNumber = computed(() => {
  const period = props.rows[0] ? periodLabel(props.rows[0].time, props.prefix) : ''
  return period ? `${props.year}-${period}` : `${props.year}`
})

const comments = computed(() => {
  const withComment = props.rows.find((row) => commentLines(row).length)
  return withComment ? commentLines(withComment) : []
})

function fileUrl(file: DatasetFile, row: DatasetRow): string {
  return downloadUrl(file, row, props.year, props.prefix)
}
</script>
