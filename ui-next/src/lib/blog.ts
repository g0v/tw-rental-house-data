import type { ImageMetadata } from 'astro'
import { getImage } from 'astro:assets'
import sharp from 'sharp'
import { getCollection, type CollectionEntry } from 'astro:content'
import { marked } from 'marked'

export type BlogPost = CollectionEntry<'blog'>

// .md 用 HTML 註解；MDX 不接受 HTML 註解，改用 JSX 註解 `{/* more */}`
const EXCERPT_SEPARATOR = /<!--more-->|\{\/\*\s*more\s*\*\/\}/

/** 分隔符之前的段落作為摘要（19 篇舊文全都有這個分隔）；MDX 開頭的 import 行不算內文 */
export function excerptMarkdown(post: BlogPost): string {
  const body = post.body ?? ''
  return body
    .split(EXCERPT_SEPARATOR)[0]!
    .replace(/^import\s.*$/gm, '')
    .trim()
}

/** 摘要的純文字版，給列表卡片用（卡片本身是連結，不能再包連結） */
export function excerptText(post: BlogPost): string {
  const html = marked.parse(excerptMarkdown(post), { async: false })
  return html
    .replace(/<[^>]+>/g, '')
    .replace(/\s+\n/g, '\n')
    .trim()
}

/** 全部文章，新在前 */
export async function sortedPosts(): Promise<BlogPost[]> {
  const posts = await getCollection('blog')
  return posts.sort(
    (a, b) => b.data.created.getTime() - a.data.created.getTime()
  )
}

/** 所有 tag，依文章順序去重 */
export function collectTags(posts: BlogPost[]): string[] {
  return [...new Set(posts.flatMap((post) => post.data.tags))]
}

/** 列表卡片的封面：三欄 grid 最寬約 380px，給 2x 螢幕到 800 就夠，build 時轉 WebP */
const CARD_COVER_WIDTHS = [400, 800]
const CARD_COVER_SIZES =
  '(min-width: 1024px) 380px, (min-width: 768px) 50vw, 100vw'

export interface CardCover {
  src: string
  srcset: string
  sizes: string
  width: number
  height: number
  /** LQIP：20px 寬 WebP 的 data URI，放大加 blur 當佔位 */
  placeholder: string
}

/** 圖片 LQIP（Low Quality Image Placeholder）：縮到 20px 寬轉 base64，約 300–600 bytes */
const LQIP_WIDTH = 20
const lqipCache = new Map<string, Promise<string>>()

export function lqip(image: ImageMetadata): Promise<string> {
  // fsPath 是 astro:assets 在 build 時掛上的原檔路徑，公開型別沒列但 image() 匯入一定有
  const path = (image as ImageMetadata & { fsPath?: string }).fsPath
  if (!path) throw new Error(`lqip: ${image.src} 沒有 fsPath，不是 src/ 內匯入的圖`)
  let cached = lqipCache.get(path)
  if (!cached) {
    cached = sharp(path)
      .resize(LQIP_WIDTH)
      .webp({ quality: 30 })
      .toBuffer()
      .then((buf) => `data:image/webp;base64,${buf.toString('base64')}`)
    lqipCache.set(path, cached)
  }
  return cached
}

/** 文章頁封面／og:image 用；og 抓 1200 寬 jpg，社群平台不一定吃 WebP */
export const OG_COVER_WIDTH = 1200

export async function ogCoverUrl(post: BlogPost, site: URL | undefined) {
  const image = await getImage({
    src: post.data.cover,
    width: OG_COVER_WIDTH,
    format: 'jpg'
  })
  return new URL(image.src, site).toString()
}

/** BlogPostList 卡片需要的欄位 */
export async function toCard(post: BlogPost) {
  const [cover, placeholder] = await Promise.all([
    getImage({
      src: post.data.cover,
      widths: CARD_COVER_WIDTHS,
      sizes: CARD_COVER_SIZES,
      format: 'webp'
    }),
    lqip(post.data.cover)
  ])
  return {
    id: post.id,
    title: post.data.title,
    author: post.data.author,
    cover: {
      src: cover.src,
      srcset: cover.srcSet.attribute,
      sizes: CARD_COVER_SIZES,
      width: cover.attributes.width,
      height: cover.attributes.height,
      placeholder
    } satisfies CardCover,
    excerpt: excerptText(post),
    createdIso: post.data.created.toISOString(),
    createdLabel: formatDate(post.data.created)
  }
}

export function formatDate(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${date.getFullYear()}/${month}/${day}`
}
