<template>
  <details class="group border-b border-rule" :open="open">
    <summary
      class="flex cursor-pointer list-none items-baseline gap-4 px-2 py-3 hover:bg-tile-pale [&::-webkit-details-marker]:hidden"
    >
      <span
        class="inline-block w-4 text-center text-sm text-ink-soft transition-transform group-open:rotate-90"
        aria-hidden="true"
        >▸</span
      >
      <h3 class="font-serif text-2xl font-bold">{{ stats.year }}</h3>
      <span class="font-mono text-sm text-ink-soft">{{ summaryLine }}</span>
      <a
        class="ml-auto text-sm text-tile-deep underline"
        :download="`${stats.year}.json`"
        :href="jsonContent"
        @click.stop
        >本表格資料下載 [JSON]</a
      >
    </summary>
    <div class="space-y-6 pt-1 pb-6 pl-2 sm:pl-10">
      <section v-if="stats.annual.length">
        <h4 class="border-b border-ink py-1 text-base font-medium">年度資料</h4>
        <DownloadTable :year="stats.year" :rows="stats.annual" prefix="" />
      </section>
      <section v-if="stats.quarterly.length">
        <h4 class="border-b border-ink py-1 text-base font-medium">每季資料</h4>
        <DownloadTable
          :year="stats.year"
          :rows="stats.quarterly"
          prefix="Q"
          id-header="季度"
        />
      </section>
      <section v-if="stats.monthly.length">
        <h4 class="border-b border-ink py-1 text-base font-medium">每月資料</h4>
        <DownloadTable
          :year="stats.year"
          :rows="stats.monthly"
          prefix="0"
          id-header="月份"
        />
      </section>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { YearStats } from '../data/stats'
import DownloadTable from './DownloadTable.vue'

const props = defineProps<{
  stats: YearStats
  /** 預設只展開最新一年 */
  open?: boolean
}>()

const summaryLine = computed(() => {
  const parts: string[] = []
  if (props.stats.annual.length) {
    parts.push('年度')
  }
  if (props.stats.quarterly.length) {
    parts.push(`${new Set(props.stats.quarterly.map((row) => row.time)).size} 季`)
  }
  if (props.stats.monthly.length) {
    parts.push(`${new Set(props.stats.monthly.map((row) => row.time)).size} 個月`)
  }
  return parts.join(' · ')
})

const jsonContent = computed(() => {
  return (
    'data:text/plain;charset=utf-8,' +
    encodeURIComponent(JSON.stringify(props.stats, null, 2))
  )
})
</script>
