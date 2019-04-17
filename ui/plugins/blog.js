export default ({ app }, inject) => {
  inject('getBlogPosts', () => {
    return process.env.blog.posts
  })
}
