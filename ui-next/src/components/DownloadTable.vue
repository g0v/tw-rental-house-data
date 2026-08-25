<template>
  <div class="overflow-x-auto">
    <table class="w-full min-w-2xl border-collapse text-sm">
      <thead>
        <tr class="border-b border-ink text-left">
          <th v-if="idHeader" class="px-3 py-2 font-medium">{{ idHeader }}</th>
          <th class="px-3 py-2 font-medium">內容</th>
          <th class="px-3 py-2 font-medium">資料集版本</th>
          <th class="px-3 py-2 font-medium">總物件數</th>
          <th
            v-for="source in sourceHeaders"
            :key="source"
            class="px-3 py-2 font-medium"
          >
            {{ source }} 物件數
          </th>
          <th class="px-3 py-2 font-medium">下載連結 / 解壓縮後大小</th>
          <th class="px-3 py-2 font-medium">附註</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.time + row.type"
          class="border-b border-rule align-top"
        >
          <td v-if="idHeader" class="px-3 py-2 font-mono">
            {{ periodLabel(row.time, prefix) || row.time }}
          </td>
          <td class="px-3 py-2">{{ row.type }}</td>
          <td class="px-3 py-2">
            <a
              class="text-tile-deep underline"
              :href="dataVerUrl(row.data_ver)"
              :title="dataVerStage(row.data_ver)"
              >{{ row.data_ver }}</a
            >
          </td>
          <td class="px-3 py-2 font-mono">
            {{ row.total_count.toLocaleString() }}
          </td>
          <td
            v-for="source in sourceHeaders"
            :key="source"
            class="px-3 py-2 font-mono"
          >
            {{ sourceCount(row, source) }}
          </td>
          <td class="px-3 py-2">
            <div v-for="file in row.files" :key="file.format ?? 'csv'" class="py-0.5">
              <a
                class="font-mono text-tile-deep underline uppercase"
                :href="fileUrl(file, row)"
                target="_blank"
                rel="noopener"
                >{{ file.format ?? 'csv' }}</a
              >
              <span class="ml-2 font-mono text-xs text-ink-soft">{{
                prettyFilesize(file.size_byte)
              }}</span>
            </div>
          </td>
          <td class="min-w-48 px-3 py-2 leading-relaxed text-ink-soft">
            <p v-if="row.quality_issue" class="text-rust">
              ⚠
              <a
                class="text-rust underline"
                :href="`/data-quality#${row.quality_issue}`"
                >此期間資料有已知品質問題</a
              >
            </p>
            <!-- eslint-disable-next-line vue/no-v-html — renderCommentHtml escapes everything but links -->
            <p
              v-for="line in commentLines(row)"
              :key="line"
              v-html="renderCommentHtml(line)"
            />
            <template v-if="!row.quality_issue && !commentLines(row).length"
              >--</template
            >
          </td>
        </tr>
      </tbody>
    </table>
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
  RELEASE_STAGE,
  type PeriodPrefix
} from '../lib/download'

const props = defineProps<{
  year: number
  rows: DatasetRow[]
  prefix: PeriodPrefix
  /** 期間欄標題（年度資料不顯示期間欄，傳空字串） */
  idHeader?: string
}>()

const sourceHeaders = computed(() => {
  const names = props.rows.flatMap((row) =>
    row.sources.map((source) => source.name)
  )
  return [...new Set(names)]
})

function sourceCount(row: DatasetRow, sourceName: string): string {
  const source = row.sources.find((item) => item.name === sourceName)
  return source ? source.count.toLocaleString() : '-'
}

function dataVerUrl(dataVer: string): string {
  return `/about-data-set/${dataVer.split(' ')[0]}`
}

function dataVerStage(dataVer: string): string {
  const stage = dataVer.split(' ')[1]
  return (stage && RELEASE_STAGE[stage.toLowerCase()]) || ''
}

function fileUrl(file: DatasetFile, row: DatasetRow): string {
  return downloadUrl(file, row, props.year, props.prefix)
}
</script>
