/* eslint-disable import/first */
// in case we need env var in this file
require('dotenv').config()

// TODO: friendly header

const isProd = process.env.NODE_ENV === 'production'

export default {
  // Target: https://go.nuxtjs.dev/config-target
  target: 'static',
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
    htmlAttrs: {
      lang: 'zh-Hant-TW'
    },
    meta: [
      { charset: 'utf-8' },
      {
        name: 'google-site-verification',
        content: 'uCUr0xYNUdjv0NqVRBNBDlnRHqkbLOmc_E8uzfkNxtY'
      },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      {
        hid: 'description',
        name: 'description',
        content:
          '「開放民間租屋資料」希望提供對租屋議題有興趣的單位，一份長期、開放，而且詳細的租屋資料集，去除有著作權與隱私疑慮的資料後，以 CC0 釋出，為台灣的租賃市場與居住議題建立研究的基礎資料。'
      },
      {
        hid: 'og:image',
        name: 'og:image',
        content: 'https://rentalhouse.g0v.ddio.io/imgs/og.png'
      }
    ],
    link: []
  },
  /*
   ** Customize the progress bar color
   */
  loading: { color: '#3B8070' },
  css: [
    '@fortawesome/fontawesome-free/css/all.css',
    'tachyons/css/tachyons.css',
    'assets/css/common.scss'
  ],

  styleResources: {
    scss: [
      '~/assets/css/variables.scss'
    ]
  },

  // Auto import components: https://go.nuxtjs.dev/config-components
  components: true,

  // Modules for dev and build (recommended): https://go.nuxtjs.dev/config-modules
  buildModules: [
    // https://go.nuxtjs.dev/eslint
    '@nuxtjs/eslint-module',
    '@nuxtjs/style-resources',
    '@nuxtjs/style-resources'
  ],

  // Modules: https://go.nuxtjs.dev/config-modules
  modules: [
    // https://go.nuxtjs.dev/axios
    '@nuxtjs/axios',
    // https://go.nuxtjs.dev/content
    '@nuxt/content',
    'vue-plausible',
    '@nuxtjs/sentry'
  ],

  // Axios module configuration: https://go.nuxtjs.dev/config-axios
  axios: {
    // Workaround to avoid enforcing hard-coded localhost:3000: https://github.com/nuxt-community/axios-module/issues/308
    baseURL: '/'
  },

  sentry: {
    dsn: isProd ? process.env.SENTRY_DSN : '',
    disableServerSide: true,
    clientIntegrations: {
      CaptureConsole: { levels: ['error', 'warn'] }
    },

    // always inject sentry methods in all env
    logMockCalls: true,
    disabled: !isProd,
    publishRelease: {
      authToken: process.env.SENTRY_AUTH_TOKEN,
      org: process.env.SENTRY_ORG,
      project: process.env.SENTRY_PROJECT,
      // Attach commits to the release (requires that the build triggered within a git repository).
      setCommits: {
        auto: true,
        ignoreMissing: true,
        ignoreEmpty: true
      }
    },
    sourceMapStyle: 'hidden-source-map',

    config: {
      // Add native Sentry config here
      // https://docs.sentry.io/platforms/javascript/guides/vue/configuration/options/
      release: process.env.GITHUB_SHA || 'dev'
    }
  },

  plausible: {
    domain: 'rentalhouse.g0v.ddio.io',
    enableAutoOutboundTracking: true
  },

  // Content module configuration: https://go.nuxtjs.dev/config-content
  content: {},

  server: {
    port: process.env.SERVER_PORT || 3000,
    host: process.env.SERVER_HOST || 'localhost'
  },

  generate: {
    concurrency: 10
  },
  plugins: [
    'plugins/vue-markdown',
    'plugins/vue-observe-visibility',
    'plugins/vue-disqus'
  ]
}
