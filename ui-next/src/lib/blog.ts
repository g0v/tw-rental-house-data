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

/** BlogPostList 卡片需要的欄位 */
export function toCard(post: BlogPost) {
  return {
    id: post.id,
    title: post.data.title,
    author: post.data.author,
    cover: post.data.cover,
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
