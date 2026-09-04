import { defineCollection } from 'astro:content'
import { glob } from 'astro/loaders'
import { z } from 'zod'

const blog = defineCollection({
  // .mdx 給要嵌互動圖表的新文章（docs/ui-roadmap.md Phase 5），舊文維持 .md
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/blog' }),
  // 封面與內文圖放 src/content/blog/imgs/，由 astro:assets 在 build 時縮圖／轉 WebP；
  // public/imgs/blog 是指向同一目錄的 symlink，讓舊站 /imgs/blog/* 絕對 URL 原樣保留
  schema: ({ image }) =>
    z.object({
      title: z.string(),
      author: z.string(),
      created: z.coerce.date(),
      /** 相對於文章檔的路徑，如 ./imgs/xxx.png */
      cover: image(),
      tags: z.array(z.string()).default([]),
      // 舊站 @nuxt/content 的殘留欄位（html: true）；Astro 本來就渲染行內 HTML，忽略即可
      config: z.object({ html: z.boolean() }).optional()
    })
})

const aboutDataSet = defineCollection({
  loader: glob({
    pattern: '**/*.md',
    base: './src/content/about-data-set',
    // 預設的 slug 化會把「0.0」變成「00」，這裡保留檔名作為版本號
    generateId: ({ entry }) => entry.replace(/\.md$/, '')
  }),
  schema: z.object({
    version: z.string(),
    released: z.coerce.date(),
    /** 適用期間，版本沿革目錄頁用 */
    period: z.string(),
    /** 變更摘要，版本沿革目錄頁用 */
    summary: z.string()
  })
})

export const collections = { blog, aboutDataSet }
