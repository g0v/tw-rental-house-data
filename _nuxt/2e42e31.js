(window.webpackJsonp=window.webpackJsonp||[]).push([[16,5,6],{534:function(t,e,r){var content=r(539);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("e9c96ef2",content,!0,{sourceMap:!1})},536:function(t,e,r){var content=r(544);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("7682f59a",content,!0,{sourceMap:!1})},538:function(t,e,r){"use strict";r(534)},539:function(t,e,r){var n=r(46)(!1);n.push([t.i,'.tag[data-v-fce54ba8]:not(:last-child):after{content:"-";margin-left:.25rem}',""]),t.exports=n},540:function(t,e,r){"use strict";r.r(e);var n={props:{tags:{required:!0,type:Array}}},o=(r(538),r(45)),component=Object(o.a)(n,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"tags"},t._l(t.tags,(function(r){return e("nuxt-link",{key:r,staticClass:"tag mr1 dim no-underline outline-0",attrs:{to:"/blog/tag/".concat(r,"/")}},[t._v(t._s(r))])})),1)}),[],!1,null,"fce54ba8",null);e.default=component.exports},543:function(t,e,r){"use strict";r(536)},544:function(t,e,r){var n=r(46)(!1);n.push([t.i,".post__cover[data-v-3c4711a7]{height:40%}.post__tail[data-v-3c4711a7]{left:2rem;height:3.5em;margin-top:1em;width:calc(100% - 4rem);background:linear-gradient(transparent,#fff 1.3em)}.post__footer[data-v-3c4711a7],.post__tail[data-v-3c4711a7]{position:absolute;bottom:calc(1rem + 1px)}.post__footer[data-v-3c4711a7]{left:1rem;height:2em;padding:.5em;width:calc(100% - 2rem);overflow:hidden}",""]),t.exports=n},547:function(t,e,r){"use strict";r.r(e);var n={props:{posts:{required:!0,type:Array}},methods:{contentCreated:function(t){return new Date(t.created).toLocaleDateString()}}},o=(r(543),r(45)),component=Object(o.a)(n,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"flex flex-wrap justify-center"},t._l(t.posts,(function(r){return e("div",{key:r.slug,staticClass:"mw6-l w-33-l w-100 fl relative"},[e("article",{staticClass:"aspect-ratio--1x1",attrs:{itemscope:"",itemtype:"http://schema.org/Article"}},[e("nuxt-link",{staticClass:"pa3 h-100 w-100 dim no-underline db absolute",attrs:{itemprop:"url",to:"/blog/post/".concat(r.slug,"/")}},[e("div",{staticClass:"post br2 ba b--moon-gray h-100 overflow-hidden"},[e("div",{staticClass:"post__cover cover center black",style:{backgroundImage:"url('".concat(r.cover,"')")}}),e("div",{staticClass:"pa3"},[e("header",{staticClass:"f4 b black",attrs:{itemprop:"name headline"}},[t._v(t._s(r.title))]),e("nuxt-content",{staticClass:"f6 black lh-copy",attrs:{itemprop:"articleBody",document:{body:r.excerpt}}})],1),e("div",{attrs:{itemprop:"publisher",itemscope:"",itemtype:"https://schema.org/Organization"}},[e("meta",{attrs:{itemprop:"name",content:"開放台灣民間租屋資料"}})]),e("div",{staticClass:"post__tail"}),e("div",{staticClass:"post__footer bt b--moon-gray flex justify-between light-silver"},[e("div",{staticClass:"dib f6",attrs:{itemprop:"author",itemscope:"",itemtype:"http://schema.org/Person"}},[e("i",{staticClass:"mr2 fa fa-user-o"}),e("span",{attrs:{itemprop:"name"}},[t._v(t._s(r.author))])]),e("div",{staticClass:"dib f6",attrs:{itemprop:"datePublished dateModified",content:r.created}},[e("i",{staticClass:"mr2 fa fa-calendar"}),t._v(t._s(t.contentCreated(r)))])])])])],1)])})),0)}),[],!1,null,"3c4711a7",null);e.default=component.exports},548:function(t,e,r){"use strict";var n=r(3),o=r(549),c=r(54),l=r(36),f=r(48),d=r(147);n({target:"Array",proto:!0},{flatMap:function(t){var e,r=l(this),n=f(r);return c(t),(e=d(r,0)).length=o(e,r,r,n,0,1,t,arguments.length>1?arguments[1]:void 0),e}})},549:function(t,e,r){"use strict";var n=r(106),o=r(48),c=r(188),l=r(66),f=function(t,e,source,r,d,m,v,h){for(var element,_,y=d,C=0,x=!!v&&l(v,h);C<r;)C in source&&(element=x?x(source[C],C,e):source[C],m>0&&n(element)?(_=o(element),y=f(t,e,element,_,y,m-1)-1):(c(y+1),t[y]=element),y++),C++;return y};t.exports=f},550:function(t,e,r){r(145)("flatMap")},559:function(t,e,r){var content=r(574);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("411daeca",content,!0,{sourceMap:!1})},573:function(t,e,r){"use strict";r(559)},574:function(t,e,r){var n=r(46)(!1);n.push([t.i,'.tag[data-v-c06c2c52]:not(:last-child):after{content:"-";margin-left:.25rem}',""]),t.exports=n},592:function(t,e,r){"use strict";r.r(e);var n=r(13),o=(r(65),r(33),r(41),r(16),r(548),r(550),r(542)),c={layout:"blog",asyncData:function(t){return Object(n.a)(regeneratorRuntime.mark((function e(){var r,n,c,l,f,d;return regeneratorRuntime.wrap((function(e){for(;;)switch(e.prev=e.next){case 0:return r=t.$content,n=t.params,t.redirect,c=n.name,e.next=4,r("blog").only(["slug","cover","title","author","created","tags","excerpt"]).where({tags:{$contains:c}}).sortBy("created","desc").fetch();case 4:return l=e.sent,e.next=7,r("blog").only(["tags"]).sortBy("created","desc").fetch();case 7:return f=e.sent,d=Object(o.uniq)(f.flatMap((function(t){return t.tags}))).filter((function(t){return t!==c})),e.abrupt("return",{posts:l,tags:d});case 10:case"end":return e.stop()}}),e)})))()},computed:{tag:function(){return this.$route.params.name}}},l=(r(573),r(45)),component=Object(l.a)(c,(function(){var t=this,e=t._self._c;return e("main",{staticClass:"w-100 mw9-l pa4 center"},[e("h1",{staticClass:"tc"},[e("span",{staticClass:"gray"},[t._v("包含")]),e("i",{staticClass:"fa fa-tag mh2"}),t._v(t._s(t.tag)),e("span",{staticClass:"gray"},[t._v("的貼文")])]),e("div",{staticClass:"tc gray f6"},[t._v("其他標籤："),e("blog-tag-list",{staticClass:"dib",attrs:{tags:t.tags}})],1),t.posts.length?e("blog-post-list",{attrs:{posts:t.posts}}):e("div",[e("div",{staticClass:"f3 b pa3 mt6 tc"},[t._v('這是國王的標籤嗎？ ~"~')]),e("nuxt-link",{staticClass:"tc db",attrs:{to:"/blog"}},[t._v("回部落格首頁")])],1)],1)}),[],!1,null,"c06c2c52",null);e.default=component.exports;installComponents(component,{BlogTagList:r(540).default,BlogPostList:r(547).default})}}]);