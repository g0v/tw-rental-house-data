import { getImage } from 'astro:assets'
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
  const cover = await getImage({
    src: post.data.cover,
    widths: CARD_COVER_WIDTHS,
    sizes: CARD_COVER_SIZES,
    format: 'webp'
  })
  return {
    id: post.id,
    title: post.data.title,
    author: post.data.author,
    cover: {
      src: cover.src,
      srcset: cover.srcSet.attribute,
      sizes: CARD_COVER_SIZES,
      width: cover.attributes.width,
      height: cover.attributes.height
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
