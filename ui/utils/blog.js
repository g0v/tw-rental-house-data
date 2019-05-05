import fs from 'fs'
import slugify from 'slugify'
import { loadFront } from 'yaml-front-matter'

const blogBase = 'blog/'

export function listPosts() {
  if (!fs.existsSync(blogBase)) {
    return []
  }
  const posts = fs
    .readdirSync(blogBase)
    .filter(file => {
      const stat = fs.statSync(`${blogBase}${file}`)
      return stat.isFile() && file.endsWith('.md')
    })
    .map(file => {
      const url = slugify(file.replace(/.md$/, ''))
      // capitalize url
      const meta = Object.assign(
        {
          created: '1970-01-01T08:00:00+08:00',
          title: '',
          tags: [],
          config: {},
          author: ''
        },
        loadFront(fs.readFileSync(`${blogBase}${file}`, 'utf-8'))
      )
      meta.created = new Date(meta.created)
      const content = meta.__content
      delete meta.__content
      return {
        url,
        meta,
        content
      }
    })
    .sort((postL, postR) => postR.meta.created - postL.meta.created)

  return posts
}

export function listRoutes() {
  const posts = listPosts()
  const tags = {}

  posts.forEach(post => {
    post.meta.tags.forEach(tag => {
      tags[tag] = true
    })
  })

  return [
    ...posts.map(post => `/blog/post/${post.url}`),
    ...Object.keys(tags).map(tag => `/blog/tag/${tag}`)
  ]
}

export default listPosts
