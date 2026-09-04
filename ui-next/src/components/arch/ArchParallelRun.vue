<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * 新舊並行（觀測層）與雙寫對帳（資料層）的三段式示意：
 * 並行前／並行中／切換後。兩層共用同一組 phase 按鈕，讓讀者看出
 * 「兩個日曆門檻是同一件事」。
 */
type Phase = 'before' | 'during' | 'after'
type Layer = 'observe' | 'data'

const phases: { key: Phase; label: string }[] = [
  { key: 'before', label: '並行前' },
  { key: 'during', label: '並行中' },
  { key: 'after', label: '切換後' }
]
const layers: { key: Layer; label: string }[] = [
  { key: 'observe', label: '觀測層：manifest 並行' },
  { key: 'data', label: '資料層：原始 HTML 雙寫' }
]

const phase = ref<Phase>('during')
const layer = ref<Layer>('observe')

// 舊的那條線：切換後變虛影；新的那條線：並行前還不存在
const oldGhost = computed(() => phase.value === 'after')
const newGhost = computed(() => phase.value === 'before')

const captions: Record<Layer, Record<Phase, string>> = {
  observe: {
    before: '四套工具各自讀資料庫、各自有 baseline，warning 分四路發到 Slack。',
    during:
      '新的 manifest＋斷言跟舊工具一起跑，讀的是同一份資料，彼此沒有共享狀態。兩邊都只觀測；唯一會讓 pipeline 停下來的 queuefinalize 獨立在外。',
    after: '連續幾天逐項一致後，刪掉舊工具的呼叫。要回退，加回來就好。'
  },
  data: {
    before: '原始 HTML 只存在資料庫，靠定期搬出去控制體積。',
    during:
      '同一份 HTML 同時寫資料庫與暫存目錄，收工時打成當日的壓縮包上 S3，再抽樣比對兩邊內容。資料庫仍是權威；打包失敗只警告，不擋 pipeline。',
    after: '資料庫停寫並清空，S3 日包成為權威；打包失敗升級為紅燈。'
  }
}
</script>

<template>
  <figure class="not-prose my-8 rounded-lg border border-rule bg-white p-4 text-ink sm:p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="inline-flex overflow-hidden rounded border border-rule text-xs sm:text-sm">
        <button
          v-for="l in layers"
          :key="l.key"
          type="button"
          class="px-3 py-1.5 transition-colors"
          :class="layer === l.key ? 'bg-tile text-white' : 'bg-paper text-ink-soft hover:bg-terrazzo'"
          :aria-pressed="layer === l.key"
          @click="layer = l.key"
        >
          {{ l.label }}
        </button>
      </div>
      <div class="inline-flex overflow-hidden rounded border border-rule font-mono text-xs sm:text-sm">
        <button
          v-for="p in phases"
          :key="p.key"
          type="button"
          class="px-3 py-1.5 transition-colors"
          :class="phase === p.key ? 'bg-ink text-paper' : 'bg-paper text-ink-soft hover:bg-terrazzo'"
          :aria-pressed="phase === p.key"
          @click="phase = p.key"
        >
          {{ p.label }}
        </button>
      </div>
    </div>

    <!-- 觀測層 -->
    <div v-if="layer === 'observe'" class="mt-6 text-xs sm:text-sm">
      <div class="mx-auto w-2/3 rounded border border-rule bg-terrazzo px-3 py-2 text-center sm:w-1/2">
        <div class="font-medium">當日資料（資料庫）</div>
        <div class="font-mono text-[11px] text-ink-soft">兩邊都只讀，不寫</div>
      </div>

      <svg class="block h-8 w-full text-ink-soft" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
        <path d="M50 0 V14 H25 V32" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" :stroke-dasharray="oldGhost ? '4 4' : undefined" :opacity="oldGhost ? 0.35 : 1" />
        <path d="M50 0 V14 H75 V32" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" :stroke-dasharray="newGhost ? '4 4' : undefined" :opacity="newGhost ? 0.35 : 1" />
      </svg>

      <div class="grid grid-cols-2 gap-3 *:min-w-0">
        <div
          class="rounded border px-3 py-2 transition-all duration-300"
          :class="oldGhost ? 'border-dashed border-rule opacity-40' : 'border-rule bg-paper'"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-x-2">
            <span class="font-medium" :class="{ 'line-through': oldGhost }">舊：四套工具</span>
            <span v-if="oldGhost" class="font-mono text-[11px] text-rust">已退役</span>
          </div>
          <ul class="mt-1 space-y-0.5 break-all font-mono text-[11px] text-ink-soft">
            <li>statscheck</li>
            <li>fill-rate monitor＋baselines</li>
            <li>distcheck＋national.json</li>
            <li>monthreport</li>
          </ul>
        </div>
        <div
          class="rounded border px-3 py-2 transition-all duration-300"
          :class="newGhost ? 'border-dashed border-rule opacity-40' : 'border-tile bg-tile-pale'"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-x-2">
            <span class="font-medium">新：manifest＋斷言</span>
            <span v-if="newGhost" class="font-mono text-[11px] text-ink-soft">尚未存在</span>
            <span v-else class="font-mono text-[11px] text-tile-deep">pure function</span>
          </div>
          <ul class="mt-1 space-y-0.5 break-all font-mono text-[11px] text-ink-soft">
            <li>manifests/&lt;date&gt;/&lt;stage&gt;.json</li>
            <li>quality/assertions.yaml</li>
            <li>動態基準：疊近幾份 manifest 即算</li>
          </ul>
        </div>
      </div>

      <svg class="block h-8 w-full text-ink-soft" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
        <path d="M25 0 V18 H50 V32" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" :stroke-dasharray="oldGhost ? '4 4' : undefined" :opacity="oldGhost ? 0.35 : 1" />
        <path d="M75 0 V18 H50 V32" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" :stroke-dasharray="newGhost ? '4 4' : undefined" :opacity="newGhost ? 0.35 : 1" />
      </svg>

      <div class="mx-auto w-2/3 rounded border border-rule bg-paper px-3 py-2 text-center sm:w-1/2">
        <div class="font-medium">Slack</div>
        <div class="font-mono text-[11px] text-ink-soft">只觀測，不擋 pipeline</div>
      </div>

      <div class="my-5 flex items-center gap-3 text-[11px] text-ink-soft">
        <span class="h-px flex-1 border-t border-dashed border-rule"></span>
        <span>獨立於兩軌之外</span>
        <span class="h-px flex-1 border-t border-dashed border-rule"></span>
      </div>

      <div class="flex flex-wrap items-stretch justify-center gap-2 font-mono">
        <div class="rounded border border-rule bg-paper px-3 py-2">queue</div>
        <div class="self-center text-ink-soft">→</div>
        <div class="rounded border border-rust bg-white px-3 py-2">
          queuefinalize
          <div class="text-[11px] text-ink-soft">seeds == terminals</div>
        </div>
        <div class="self-center text-ink-soft">→</div>
        <div class="rounded border border-rust bg-rust px-3 py-2 text-white">紅＝停</div>
      </div>
      <div class="mt-2 text-center text-[11px] text-ink-soft">唯一的硬閘門，三個階段都一樣</div>
    </div>

    <!-- 資料層 -->
    <div v-else class="mt-6 text-xs sm:text-sm">
      <div class="mx-auto w-2/3 rounded border border-rule bg-terrazzo px-3 py-2 text-center sm:w-1/2">
        <div class="font-medium">detail 爬蟲</div>
        <div class="font-mono text-[11px] text-ink-soft">每頁原始 HTML</div>
      </div>

      <svg class="block h-8 w-full text-ink-soft" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
        <path d="M50 0 V14 H25 V32" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" :stroke-dasharray="oldGhost ? '4 4' : undefined" :opacity="oldGhost ? 0.35 : 1" />
        <path d="M50 0 V14 H75 V32" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" :stroke-dasharray="newGhost ? '4 4' : undefined" :opacity="newGhost ? 0.35 : 1" />
      </svg>

      <div class="grid grid-cols-2 gap-3 *:min-w-0">
        <div
          class="rounded border px-3 py-2 transition-all duration-300"
          :class="oldGhost ? 'border-dashed border-rule opacity-40' : 'border-rule bg-paper'"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-x-2">
            <span class="break-all font-mono" :class="{ 'line-through': oldGhost }">HouseEtc.detail_raw</span>
            <span v-if="oldGhost" class="font-mono text-[11px] text-rust">停寫、清空</span>
            <span v-else class="font-mono text-[11px] text-tile-deep">權威</span>
          </div>
          <div class="mt-1 text-[11px] text-ink-soft">資料庫，靠 rawoffload／housekeep 定期搬出去</div>
        </div>
        <div
          class="rounded border px-3 py-2 transition-all duration-300"
          :class="newGhost ? 'border-dashed border-rule opacity-40' : 'border-tile bg-tile-pale'"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-x-2">
            <span class="break-all font-mono">raw/&lt;vendor&gt;/&lt;date&gt;.tar.zst</span>
            <span v-if="newGhost" class="font-mono text-[11px] text-ink-soft">尚未存在</span>
            <span v-else-if="phase === 'during'" class="font-mono text-[11px] text-ink-soft">副本</span>
            <span v-else class="font-mono text-[11px] text-tile-deep">權威</span>
          </div>
          <div class="mt-1 font-mono text-[11px] text-ink-soft">scratch/ → rawpack → ＋index → S3</div>
        </div>
      </div>

      <div class="mt-3 h-6 text-center font-mono text-[11px]" :class="phase === 'during' ? 'text-tile-deep' : 'text-transparent'">
        ◄──── 抽樣比對 byte 一致 ────►
      </div>

      <div class="my-5 flex items-center gap-3 text-[11px] text-ink-soft">
        <span class="h-px flex-1 border-t border-dashed border-rule"></span>
        <span>打包失敗時</span>
        <span class="h-px flex-1 border-t border-dashed border-rule"></span>
      </div>

      <div class="flex flex-wrap items-stretch justify-center gap-2 font-mono">
        <div class="rounded border border-rule bg-paper px-3 py-2">rawpack 失敗</div>
        <div class="self-center text-ink-soft">→</div>
        <div v-if="phase === 'after'" class="rounded border border-rust bg-rust px-3 py-2 text-white">紅＝停</div>
        <div v-else class="rounded border border-rule bg-white px-3 py-2">
          保留 scratch、只警告
          <div class="text-[11px] text-ink-soft">pipeline 續走，事後補打</div>
        </div>
      </div>
    </div>

    <figcaption class="mt-5 border-t border-rule pt-3 text-xs leading-relaxed text-ink-soft sm:text-sm">
      {{ captions[layer][phase] }}
    </figcaption>
  </figure>
</template>
