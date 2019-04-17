import fs from 'fs'
import markdownIt from 'markdown-it'
import slugify from 'slugify'
import { loadFront } from 'yaml-front-matter'

const blogBase = 'blog/'

const md = markdownIt()

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
          tag: [],
          author: ''
        },
        loadFront(fs.readFileSync(`${blogBase}${file}`, 'utf-8'))
      )
      meta.created = new Date(meta.created)
      const content = md.render(meta.__content)
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

export default listPosts
