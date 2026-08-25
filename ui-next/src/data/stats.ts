import { z } from 'zod'

import def2018 from './stats/2018.json'
import def2019 from './stats/2019.json'
import def2020 from './stats/2020.json'
import def2021 from './stats/2021.json'
import def2022 from './stats/2022.json'
import def2023 from './stats/2023.json'
import def2024 from './stats/2024.json'
import def2025 from './stats/2025.json'
import def2026 from './stats/2026.json'

const sourceSchema = z.object({
  name: z.string(),
  count: z.number().int().nonnegative()
})

const fileSchema = z.object({
  // 2018 有兩列缺 format（以 type: 'csv' 表示），顯示時視為 csv
  format: z.enum(['csv', 'json']).optional(),
  type: z.string().optional(),
  size_byte: z.number().int().positive(),
  // 絕大多數為 { isS3: true }，2018 年少數檔案是完整 URL 字串
  download_url: z.union([z.url(), z.object({ isS3: z.literal(true) })])
})

const rowSchema = z.object({
  schema_ver: z.string(),
  // 「0.3」或「0.1 Beta」，空白後為釋出階段標記
  data_ver: z.string(),
  // 年度資料固定為 '1'；季為 1–4、月為 1–12，皆無前導零
  time: z.string().regex(/^\d{1,2}$/),
  type: z.enum(['原始資料', '消除重複住宅']),
  total_count: z.number().int().nonnegative(),
  sources: z.array(sourceSchema).min(1),
  files: z.array(fileSchema).min(1),
  comment: z.union([z.string(), z.array(z.string())]).optional(),
  // /data-quality 時間軸總表的錨點 id，設了就會在檔案庫列上顯示品質警示
  quality_issue: z.string().optional()
})

const yearStatsSchema = z.object({
  // 2018–2020 的檔案沒有 year 欄位，以檔名為準（見下方 loadYear）
  year: z.number().int().optional(),
  annual: z.array(rowSchema),
  quarterly: z.array(rowSchema),
  monthly: z.array(rowSchema)
})

export type DatasetSource = z.infer<typeof sourceSchema>
export type DatasetFile = z.infer<typeof fileSchema>
export type DatasetRow = z.infer<typeof rowSchema>
export type YearStats = z.infer<typeof yearStatsSchema> & { year: number }

export type DatasetCategory = 'annual' | 'quarterly' | 'monthly'

function loadYear(year: number, raw: unknown): YearStats {
  const parsed = yearStatsSchema.parse(raw)
  if (parsed.year !== undefined && parsed.year !== year) {
    throw new Error(`stats/${year}.json 的 year 欄位是 ${parsed.year}`)
  }
  return { ...parsed, year }
}

/** 全部年度統計，新在前 */
export const allYearStats: YearStats[] = [
  loadYear(2026, def2026),
  loadYear(2025, def2025),
  loadYear(2024, def2024),
  loadYear(2023, def2023),
  loadYear(2022, def2022),
  loadYear(2021, def2021),
  loadYear(2020, def2020),
  loadYear(2019, def2019),
  loadYear(2018, def2018)
]

export interface LatestRelease {
  year: number
  /** 該期間的原始 + 消除重複列（time 相同） */
  rows: DatasetRow[]
}

/** 某類資料的最新一期（跨年份往回找） */
export function latestRelease(category: DatasetCategory): LatestRelease | null {
  for (const yearStats of allYearStats) {
    const rows = yearStats[category]
    if (rows.length) {
      const lastTime = rows[rows.length - 1]!.time
      return {
        year: yearStats.year,
        rows: rows.filter((row) => row.time === lastTime)
      }
    }
  }
  return null
}
