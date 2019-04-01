module.exports = {
  /*
  ** Headers of the page
  */
  head: {
    titleTemplate: (origTitle) => {
      if (origTitle) {
        return `${origTitle} | 開放台灣民間租屋資料`
      } else {
        return '開放台灣民間租屋資料'
      }
    },
    meta: [
      { charset: 'utf-8' },
      { name: 'google-site-verification', content: 'uCUr0xYNUdjv0NqVRBNBDlnRHqkbLOmc_E8uzfkNxtY' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      {
        hid: 'description',
        name: 'description',
        content: '「開放民間租屋資料」希望提供對租屋議題有興趣的單位，一份長期、開放，而且詳細的租屋資料集，去除有著作權與隱私疑慮的資料後，以 CC0 釋出，為台灣的租賃市場與居住議題建立研究的基礎資料。'
      },
      { hid: 'og:image', name: 'og:image', content: 'https://rentalhouse.g0v.ddio.io/imgs/og.png'}
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
    }
  },
  plugins: [
    '~/plugins/vue-markdown',
    '~/plugins/vue-observe-visibility',
    '~/plugins/vue-disqus'
  ]
}
