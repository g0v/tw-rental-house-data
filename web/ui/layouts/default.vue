<template lang="pug">
  .wrapper.flex.flex-column
    header.bb.b--black-20.flex.items-baseline.pa2.ph3
      .header__logo.pa2.f4.b 開放台灣民間租屋資料
      nuxt-link.header__menu(to="/download") 打包回家玩
      nuxt-link.header__menu(to="/about-data-set") 關於資料集
    nuxt.flex-auto
    footer.bt.b--black-20.pa3.flex.space-between
      section
        p.pa1.ma0
        | 本網站的所有資料，除另外註明，皆以 
        a(href='https://creativecommons.org/publicdomain/zero/1.0/deed.zh_TW') CC0
        |  拋棄一切著作相關權利，提供公眾使用。
        p.pa1.ma0
        | 若有使用上的疑問，歡迎於網站留言或
        a(href="mailto:open-tw-rental-house@ddio.io") 來信
        | 詢問。
</template>
<style lang="scss">
.wrapper {
  min-height: 100vh;
}

.header__menu {
  padding: 0.5rem;
  margin-left: 1rem;
  color: #555;
  text-decoration: none;

  &:hover, &.nuxt-link-active {
    color: black;
  }
}
</style>