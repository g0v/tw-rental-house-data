import rss from '@astrojs/rss'
import type { APIContext } from 'astro'
import { excerptText, sortedPosts } from '../lib/blog'
import { SITE_NAME } from '../lib/site'

export async function GET(context: APIContext) {
  const posts = await sortedPosts()
  return rss({
    title: `${SITE_NAME}部落格`,
    description:
      '開放台灣民間租屋資料的公告與部落格：資料釋出、資料品質紀錄、專案開發。',
    site: context.site!,
    items: posts.map((post) => ({
      title: post.data.title,
      pubDate: post.data.created,
      description: excerptText(post),
      link: `/blog/post/${post.id}/`
    })),
    customData: '<language>zh-tw</language>'
  })
}
