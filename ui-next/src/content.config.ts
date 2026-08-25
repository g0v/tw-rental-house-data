import { defineCollection } from 'astro:content'
import { glob } from 'astro/loaders'
import { z } from 'zod'

const blog = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/blog' }),
  schema: z.object({
    title: z.string(),
    author: z.string(),
    created: z.coerce.date(),
    /** 站內絕對路徑，如 /imgs/blog/xxx.png */
    cover: z.string().startsWith('/'),
    tags: z.array(z.string()).default([]),
    // 舊站 @nuxt/content 的殘留欄位（html: true）；Astro 本來就渲染行內 HTML，忽略即可
    config: z.object({ html: z.boolean() }).optional()
  })
})

export const collections = { blog }
