<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * 儲存演變：資料庫一格一格變小、S3 目錄樹一格一格長出來，
 * 每一步同時退役一批工具。資料來源＝docs/architecture-roadmap.md 附錄
 * 〈儲存演變對照〉；Phase 4 各步有觸發條件才做。
 */
type TableState = 'active' | 'changed' | 'stopped' | 'retired'

interface Table {
  id: string
  name: string
  note: string
}
interface Step {
  key: string
  phase: string
  title: string
  desc: string
  trigger?: boolean
  changes: Record<string, { state: TableState; note?: string }>
  s3: string[]
  retire: string[]
}

const tables: Table[] = [
  { id: 'house', name: 'House', note: '物件現值（原地覆寫）' },
  { id: 'house_ts', name: 'HouseTS', note: '每日快照' },
  { id: 'etc_raw', name: 'HouseEtc.detail_raw', note: '原始 HTML' },
  { id: 'etc_list', name: 'HouseEtc.list_dict', note: '列表解析結果' },
  { id: 'etc_dict', name: 'HouseEtc.detail_dict', note: '詳細頁解析結果' },
  { id: 'request_ts', name: 'RequestTS', note: '待爬 queue' },
  { id: 'stats', name: 'Stats', note: '每日統計' }
]

const steps: Step[] = [
  {
    key: 'now',
    phase: '現況',
    title: '八月重啟時',
    desc: '原始 HTML、解析結果、快照全部在資料庫裡；queue 用「刪除一列」代表完成。S3 上只有公開的月 zip。',
    changes: {},
    s3: ['publish/<year>/[YYYYMM]….zip'],
    retire: []
  },
  {
    key: 'p1',
    phase: 'Phase 1',
    title: 'queue 狀態機＋manifest',
    desc: 'request_ts 加上狀態欄，終結的列先留著、之後滾動清理；Stats 停止新增，職責交給 manifest。四套品質工具收成一個機制。',
    changes: {
      request_ts: { state: 'changed', note: '＋status／attempts／error' },
      stats: { state: 'stopped', note: '停止新增' }
    },
    s3: ['manifests/<date>/<stage>.json'],
    retire: ['statscheck', 'fill-rate monitor', 'distcheck', 'monthreport（改讀 manifest）']
  },
  {
    key: 'p3-1',
    phase: 'Phase 3',
    title: '原始 HTML 出資料庫',
    desc: 'pipeline 直接把當天的 HTML 打成按日分區的壓縮檔上 S3；資料庫停寫並清空，體積從此不再成長。',
    changes: { etc_raw: { state: 'stopped', note: '停寫、清空' } },
    s3: ['raw/<vendor>/<date>.tar.zst ＋ index'],
    retire: ['rawoffload', 'housekeep（raw 半邊）']
  },
  {
    key: 'p3-2',
    phase: 'Phase 3',
    title: '單一 flow 定義',
    desc: '四套排程機制收成一份 stage 定義，完成判據＝產出檔存在。不動資料庫與 S3，退役的是檔案系統上的進度檔、stop marker 和 log 字串契約。',
    changes: {},
    s3: [],
    retire: ['go.sh／orchestrate.sh', 'progress json', 'batch marker', 'log 字串契約']
  },
  {
    key: '4a',
    phase: 'Phase 4',
    trigger: true,
    title: '列表結果檔案化',
    desc: '列表頁的解析結果改成每日一個檔，指紋、缺席天數這些欄位跟著一起走。',
    changes: { etc_list: { state: 'stopped', note: '停寫' } },
    s3: ['list/<vendor>/<date>.jsonl.zst'],
    retire: []
  },
  {
    key: '4b',
    phase: 'Phase 4',
    trigger: true,
    title: '解析結果 parquet 化',
    desc: '詳細頁解析結果出資料庫，HouseEtc 整張退役；修 parser 從「重放工具」變成「重跑 parse 這個 stage」。',
    changes: {
      etc_dict: { state: 'retired' },
      etc_raw: { state: 'retired' },
      etc_list: { state: 'retired' }
    },
    s3: ['parsed/<vendor>/<date>.parquet'],
    retire: ['rerun 工具']
  },
  {
    key: '4c',
    phase: 'Phase 4',
    trigger: true,
    title: '每日快照 parquet 化',
    desc: 'HouseTS 退役；沒爬到的物件沿用昨天的值，變成 snapshot 這個 stage 的定義本身，不再需要另外合成。',
    changes: { house_ts: { state: 'retired' } },
    s3: ['snapshot/<date>.parquet'],
    retire: ['synthts', 'archivehistory', 'housekeep（整支）']
  },
  {
    key: '4d',
    phase: 'Phase 4',
    trigger: true,
    title: '出租狀態推導出資料庫',
    desc: 'deal 狀態改由每日快照推導；House 的現值就是最新一份快照，整張退役。',
    changes: { house: { state: 'retired' } },
    s3: ['deals/<date>.parquet'],
    retire: ['syncstateful']
  },
  {
    key: '4e',
    phase: 'Phase 4',
    trigger: true,
    title: '資料庫只剩 queue',
    desc: 'RDS 只剩一張 queue 表，或乾脆換成 SQLite；S3 成為唯一的真相來源，匯出與統計改掃分區檔案。',
    changes: {},
    s3: [],
    retire: []
  }
]

const index = ref(2)
const step = computed(() => steps[index.value]!)
const isLast = computed(() => index.value === steps.length - 1)

/** 每張表到目前這一步的狀態（取最後一次覆寫） */
const tableStates = computed(() => {
  const states: Record<string, { state: TableState; note?: string }> = {}
  for (const t of tables) states[t.id] = { state: 'active' }
  for (let i = 0; i <= index.value; i += 1) {
    Object.assign(states, steps[i]!.changes)
  }
  return states
})

/** S3 目錄樹：到目前這一步為止的全部，標記哪些是這一步新增 */
const s3Tree = computed(() =>
  steps.slice(0, index.value + 1).flatMap((s, i) =>
    s.s3.map((path) => ({ path, isNew: i === index.value }))
  )
)

/** 退役工具：到目前這一步為止的全部 */
const retired = computed(() =>
  steps.slice(0, index.value + 1).flatMap((s, i) =>
    s.retire.map((name) => ({ name, isNew: i === index.value }))
  )
)

const tableClass: Record<TableState, string> = {
  active: 'border-rule bg-terrazzo',
  changed: 'border-tile bg-tile-pale',
  stopped: 'border-dashed border-rule bg-white opacity-70',
  retired: 'border-dashed border-rule bg-white opacity-25'
}
</script>

<template>
  <figure class="not-prose my-8 rounded-lg border border-rule bg-white p-4 text-ink sm:p-6">
    <!-- 時間軸 -->
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="rounded border border-rule bg-paper px-2 py-1 font-mono text-xs hover:bg-terrazzo disabled:opacity-30"
        :disabled="index === 0"
        aria-label="上一步"
        @click="index -= 1"
      >
        ←
      </button>
      <ol class="flex flex-1 items-center gap-1">
        <li
          v-for="(s, i) in steps"
          :key="s.key"
          class="flex flex-1 items-center gap-1"
        >
          <button
            type="button"
            class="h-3 w-full rounded-sm transition-colors"
            :class="[
              i <= index ? (s.trigger ? 'bg-tile/50' : 'bg-tile') : 'bg-terrazzo',
              i === index ? 'ring-2 ring-ink ring-offset-1' : ''
            ]"
            :title="`${s.phase}：${s.title}`"
            :aria-label="`${s.phase}：${s.title}`"
            @click="index = i"
          />
          <span
            v-if="i === 3"
            class="h-5 border-l border-dashed border-ink-soft"
            aria-hidden="true"
          ></span>
        </li>
      </ol>
      <button
        type="button"
        class="rounded border border-rule bg-paper px-2 py-1 font-mono text-xs hover:bg-terrazzo disabled:opacity-30"
        :disabled="isLast"
        aria-label="下一步"
        @click="index += 1"
      >
        →
      </button>
    </div>
    <div class="mt-1 flex justify-between px-8 font-mono text-[11px] text-ink-soft">
      <span>Phase 1–3：外殼（九月）</span>
      <span>Phase 4：本體（有觸發條件才做）</span>
    </div>

    <div class="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span class="font-mono text-xs text-tile-deep">{{ step.phase }}</span>
      <span class="font-serif text-lg font-bold">{{ step.title }}</span>
      <span v-if="step.trigger" class="rounded bg-terrazzo px-1.5 py-0.5 font-mono text-[11px] text-ink-soft">觸發式</span>
    </div>
    <p class="mt-1 text-xs leading-relaxed text-ink-soft sm:text-sm">{{ step.desc }}</p>

    <!-- DB vs S3 -->
    <div class="mt-5 grid gap-4 text-xs sm:grid-cols-2 sm:text-sm">
      <div class="rounded border border-rule p-3">
        <div class="flex items-baseline justify-between">
          <span class="font-medium">資料庫（RDS）</span>
          <span class="font-mono text-[11px] text-ink-soft">{{ isLast ? '只剩 queue' : '可變狀態' }}</span>
        </div>
        <ul class="mt-2 space-y-1.5">
          <li
            v-for="t in tables"
            :key="t.id"
            class="rounded border px-2 py-1 transition-all duration-300"
            :class="tableClass[tableStates[t.id]!.state]"
          >
            <div class="flex items-baseline justify-between gap-2">
              <span
                class="font-mono"
                :class="{ 'line-through': tableStates[t.id]!.state === 'retired' }"
                >{{ t.name }}</span
              >
              <span
                v-if="tableStates[t.id]!.note"
                class="font-mono text-[11px]"
                :class="tableStates[t.id]!.state === 'changed' ? 'text-tile-deep' : 'text-rust'"
                >{{ tableStates[t.id]!.note }}</span
              >
              <span
                v-else-if="tableStates[t.id]!.state === 'retired'"
                class="font-mono text-[11px] text-rust"
                >退役</span
              >
            </div>
            <div class="text-[11px] text-ink-soft">{{ t.note }}</div>
          </li>
        </ul>
      </div>

      <div class="rounded border border-rule p-3">
        <div class="flex items-baseline justify-between">
          <span class="font-medium">S3</span>
          <span class="font-mono text-[11px] text-ink-soft">{{ isLast ? '唯一真相來源' : '不可變、按日分區' }}</span>
        </div>
        <ul class="mt-2 space-y-1 font-mono">
          <li
            v-for="node in s3Tree"
            :key="node.path"
            class="flex items-baseline gap-2 rounded px-2 py-1 transition-colors duration-300"
            :class="node.isNew ? 'bg-tile-pale text-tile-deep' : 'text-ink'"
          >
            <span class="text-ink-soft" aria-hidden="true">{{ node.isNew ? '＋' : '├' }}</span>
            <span class="break-all">{{ node.path }}</span>
          </li>
        </ul>
        <div v-if="step.s3.length === 0 && !isLast" class="mt-2 px-2 text-[11px] text-ink-soft">
          這一步不動 S3
        </div>
      </div>
    </div>

    <!-- 退役工具 -->
    <div class="mt-4 rounded border border-rule bg-paper p-3 text-xs sm:text-sm">
      <div class="flex items-baseline justify-between">
        <span class="font-medium">跟著退役的工具</span>
        <span class="font-mono text-[11px] text-ink-soft">維護面積隨儲存收斂</span>
      </div>
      <div v-if="retired.length" class="mt-2 flex flex-wrap gap-1.5 font-mono text-[11px]">
        <span
          v-for="tool in retired"
          :key="tool.name"
          class="rounded border px-1.5 py-0.5 transition-colors duration-300"
          :class="tool.isNew ? 'border-tile bg-tile-pale text-tile-deep' : 'border-rule bg-white text-ink-soft line-through'"
          >{{ tool.name }}</span
        >
      </div>
      <div v-else class="mt-2 text-[11px] text-ink-soft">還沒有</div>
    </div>

    <figcaption class="mt-5 border-t border-rule pt-3 text-xs leading-relaxed text-ink-soft sm:text-sm">
      按左右箭頭，看資料庫怎麼一格一格變小、S3 目錄樹怎麼長出來。每一步停下來都是完整可運作的系統；Phase 4 各步各有觸發條件，很可能永遠只做一部份。
    </figcaption>
  </figure>
</template>
