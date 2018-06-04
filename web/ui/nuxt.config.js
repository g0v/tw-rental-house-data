module.exports = {
  /*
  ** Headers of the page
  */
  head: {
    titleTemplate: origTitle => {
      if (origTitle) {
        return `${origTitle} | 開放台灣民間租屋資料`
      } else {
        return '開放台灣民間租屋資料'
      }
    },
    meta: [
      { charset: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { hid: 'description', name: 'description', content: '開放台灣民間租屋資料' }
    ],
    link: [
    ]
  },
  /*
  ** Customize the progress bar color
  */
  loading: { color: '#3B8070' },
  css: [
    'normalize.css/normalize.css',
    'tachyons/css/tachyons.css',
    'assets/css/common.scss'
  ],
  /*
  ** Build configuration
  */
  build: {
    /*
    ** Run ESLint on save
    */
    extend (config, { isDev, isClient }) {
      if (isDev && isClient) {
        config.module.rules.push({
          enforce: 'pre',
          test: /\.(js|vue)$/,
          loader: 'eslint-loader',
          exclude: /(node_modules)/
        })
      }
    },
    vendor: [
      'lodash',
      'filesize',
      'vue-markdown',
      'intersection-observer',
      'vue-observe-visibility',
      'vue-disqus'
    ]
  },
  plugins: [
    '~/plugins/vue-markdown',
    '~/plugins/vue-observe-visibility',
    '~/plugins/vue-disqus'
  ]
}
