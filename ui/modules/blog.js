import path from 'path'
import listPosts from '../utils/blog'

export default function DocsModule(moduleOpts) {
  this.options.env.blog = {
    posts: listPosts()
  }
  this.addPlugin(path.resolve(__dirname, '../plugins/blog.js'))
}
