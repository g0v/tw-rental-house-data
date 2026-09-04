<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * make 式 flow runner：目標是檔案、檔案在就跳過、--from 從任一 stage 續跑。
 * stage 清單是 twrh-dataset/flow.py 的簡化版（略去 synthts／sync／stats／logs）。
 */
interface Stage {
  name: string
  cmd: string
  out: string
  kind: 'artifact' | 'stamp'
  gate?: boolean
}

const stages: Stage[] = [
  { name: 'list', cmd: 'scrapy crawl list591', out: 'list.done', kind: 'stamp' },
  { name: 'seed', cmd: '由列表產生 detail 請求', out: 'seed.done', kind: 'stamp' },
  { name: 'detail', cmd: 'scrapy crawl detail591', out: 'detail.done', kind: 'stamp' },
  { name: 'queuefinalize', cmd: 'seeds == terminals，不等就紅', out: 'queuefinalize.done', kind: 'stamp', gate: true },
  { name: 'rawpack', cmd: 'rawpack --reconcile', out: 'raws/<vendor>/<date>.tar.zst', kind: 'artifact' },
  { name: 'manifest', cmd: 'manage.py manifest', out: 'manifests/<date>/{list,detail,snapshot}.json', kind: 'artifact' },
  { name: 'quality', cmd: 'qualitycheck', out: 'quality.done', kind: 'stamp' },
  { name: 'export', cmd: 'export -p（月底才有動作）', out: 'publish/<year>/[YYYYMM]….zip', kind: 'artifact' }
]

const from = ref(2)

const command = computed(() => `flow.py run --date <date> --from ${stages[from.value]!.name}`)

/** 用 Makefile 語法重述同一份定義：目標＝產出檔，先決條件＝上一個 stage 的產出檔 */
const makeTarget = (s: Stage) =>
  s.kind === 'stamp'
    ? `$(F)/${s.out}`
    : s.out.replace('<date>', '$(DATE)').replace('<vendor>', '591').replace('<year>', '$(YEAR)')

const makefile = computed(() =>
  stages.map((s, i) => {
    const prev = i === 0 ? '' : ` ${makeTarget(stages[i - 1]!)}`
    return { name: s.name, line: `${makeTarget(s)}:${prev}`, recipe: s.cmd, skip: i < from.value }
  })
)
</script>

<template>
  <figure class="not-prose my-8 rounded-lg border border-rule bg-white p-4 text-ink sm:p-6">
    <div class="text-xs text-ink-soft sm:text-sm">點一個 stage，當作從那裡續跑：</div>

    <div class="mt-3 overflow-x-auto rounded bg-ink px-3 py-2 font-mono text-xs text-paper">
      <span class="text-ink-soft">$</span> {{ command }}
    </div>

    <!-- minmax(0,…)：不讓 <pre> 的長行把左欄擠扁 -->
    <div class="mt-5 grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <!-- stage 鏈 -->
      <ol class="min-w-0 text-xs sm:text-sm">
        <li v-for="(s, i) in stages" :key="s.name">
          <button
            type="button"
            class="w-full rounded border px-3 py-2 text-left transition-all duration-200"
            :class="[
              i < from ? 'border-dashed border-rule bg-white opacity-50' : s.gate ? 'border-rust bg-white' : 'border-tile bg-tile-pale',
              i === from ? 'ring-2 ring-ink ring-offset-1' : ''
            ]"
            :aria-pressed="i === from"
            @click="from = i"
          >
            <div class="flex items-baseline justify-between gap-2">
              <span class="font-mono font-medium">{{ s.name }}</span>
              <span class="shrink-0 whitespace-nowrap font-mono text-[11px]" :class="i < from ? 'text-ink-soft' : s.gate ? 'text-rust' : 'text-tile-deep'">
                <template v-if="i < from">✓ 產出檔在，跳過</template>
                <template v-else-if="i === from">--from 從這裡</template>
                <template v-else-if="s.gate">硬閘門</template>
                <template v-else>會跑</template>
              </span>
            </div>
            <div class="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[11px] text-ink-soft">
              <span class="font-mono break-all">{{ s.kind === 'stamp' ? `logs/flow/<date>/${s.out}` : s.out }}</span>
              <span class="rounded bg-terrazzo px-1 font-mono">{{ s.kind === 'artifact' ? 'artifact' : 'stamp' }}</span>
            </div>
          </button>
          <div v-if="i < stages.length - 1" class="ml-5 h-3 border-l" :class="i < from ? 'border-dashed border-rule' : 'border-tile'" aria-hidden="true"></div>
        </li>
      </ol>

      <!-- Makefile 版 -->
      <div class="min-w-0">
        <div class="mb-1 text-[11px] text-ink-soft">如果用 make 寫，大概長這樣（純修辭，實際是 flow.py）：</div>
        <pre class="overflow-x-auto rounded bg-ink p-3 font-mono text-[11px] leading-relaxed text-paper"><span class="text-ink-soft">F := logs/flow/$(DATE)   # stamp 檔目錄</span>

<template v-for="m in makefile" :key="m.name"><span :class="m.skip ? 'text-ink-soft line-through' : 'text-tile-pale'">{{ m.line }}</span><span v-if="m.skip" class="text-ink-soft">   # up to date</span>
<span :class="m.skip ? 'text-ink-soft' : 'text-paper'">	{{ m.recipe }}</span>

</template></pre>
      </div>
    </div>

    <figcaption class="mt-5 border-t border-rule pt-3 text-xs leading-relaxed text-ink-soft sm:text-sm">
      每個 stage 的完成判據是「產出檔在不在」，跟 make 的 target 一樣；stamp 檔是還沒檔案化的 stage 的過渡做法。續跑、重跑、進度追蹤都不用另外做。
    </figcaption>
  </figure>
</template>
