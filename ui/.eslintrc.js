module.exports = {
  root: true,
  env: {
    browser: true,
    node: true
  },
  parserOptions: {
    parser: '@babel/eslint-parser',
    requireConfigFile: false
  },
  extends: [
    '@nuxtjs',
    'plugin:nuxt/recommended'
  ],
  plugins: [
  ],
  // add your custom rules here
  rules: {
    'no-console': ['error', { allow: ['warn', 'error', 'info'] }]
  },
  overrides: [
    {
      files: ['pages/**/*.vue', 'layouts/*.vue'],
      rules: {
        'vue/multi-word-component-names': 'off'
      }
    }
  ]
}
