export default async (ctx, inject) => {
  inject('getBlogPosts', () => {
    return process.env.blog.posts
  })
  // copy-paste from https://github.com/nuxt/nuxt.js/issues/240
  await ctx.store.dispatch('nuxtClientInit', ctx)
}
