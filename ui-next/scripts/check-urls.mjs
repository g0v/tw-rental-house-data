// URL 保留清單驗收（docs/ui-roadmap.md〈URL 保留清單〉）
// 用法：node scripts/check-urls.mjs [dist 路徑，預設 ./dist]
import { existsSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const dist = process.argv[2] ?? new URL('../dist', import.meta.url).pathname

const BLOG_SLUGS = [
  '2019-anniversary',
  '2020-09-automation-help-needed',
  '2021-annual-data',
  '2024-sep-return',
  '2024-system-upgrading',
  '2024-twrh-pipeline',
  '2025-back-to-beta',
  '2025-nov-release',
  '2025-oct-release',
  'clickhouse-local-aggregation',
  'data-issue-2019-00',
  'data-issue-2019-01',
  'data-issue-2019-02',
  'data-issue-2019-03',
  'data-issue-2021-00',
  'data-issue-2021-01',
  'data-issue-2023-00',
  'data-issue-2023-01',
  'resurrection'
]

const TAGS = [
  '591租屋網',
  '定期紀錄',
  '封面圖片使用 AI 生成',
  '技術文件',
  '資料品質',
  '關於'
]

const pages = [
  '/',
  '/download',
  '/blog',
  // 依 IA 拍板，/about-data-set 由 redirect 改為版本沿革目錄頁（仍須存在）
  '/about-data-set',
  '/about-data-set/0.0',
  '/about-data-set/0.1',
  '/about-data-set/0.2',
  '/about-data-set/0.3',
  // 這兩條為 redirect 頁（meta refresh 到 /blog）
  '/blog/post',
  '/blog/tag',
  ...BLOG_SLUGS.map((slug) => `/blog/post/${slug}`),
  ...TAGS.map((tag) => `/blog/tag/${tag}`)
]

const files = [
  '/CNAME',
  '/imgs/og.png',
  '/imgs/download-og.png',
  ...readdirSync(
    new URL('../public/imgs/blog', import.meta.url).pathname
  ).map((name) => `/imgs/blog/${name}`)
]

let failed = 0

for (const page of pages) {
  const target = join(dist, page, 'index.html')
  if (!existsSync(target)) {
    failed += 1
    console.error(`MISSING page  ${page}  (${target})`)
  }
}

for (const file of files) {
  const target = join(dist, file)
  if (!existsSync(target)) {
    failed += 1
    console.error(`MISSING asset ${file}`)
  }
}

if (failed) {
  console.error(`\n${failed} 條路徑缺漏`)
  process.exit(1)
}
console.log(
  `URL 保留清單驗收通過：${pages.length} 個頁面 + ${files.length} 個靜態資產`
)
