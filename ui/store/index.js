export const state = () => ({
  blogPosts: []
})

export const mutations = {
  updateBlogPosts(state, posts) {
    state.blogPosts = posts
  }
}

export const actions = {
  nuxtServerInit({ commit }) {
    if (process.server) {
      const { listPosts } = require('@/utils/blog')
      commit('updateBlogPosts', listPosts())
    } else {
      commit('updateBlogPosts', this.$getBlogPosts())
    }
  }
}
