(window.webpackJsonp=window.webpackJsonp||[]).push([[22],{542:function(t,e,r){var content=r(555);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("3a6d37de",content,!0,{sourceMap:!1})},553:function(t,e,r){var content=r(565);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("2259e751",content,!0,{sourceMap:!1})},554:function(t,e,r){"use strict";r(542)},555:function(t,e,r){var n=r(46)(!1);n.push([t.i,"",""]),t.exports=n},558:function(t,e,r){"use strict";r.r(e);r(534),r(83);var defs=r(537),n={props:{dataset:{type:Object,required:!0},year:{type:Number,required:!0},period:{type:String,required:!0}},methods:{downloadUrl:function(t){console.warn(t);var e=t.download_url;if("string"==typeof e)return e;if(e.isS3){var r="原始資料"===this.dataset.type?"Raw":"Deduplicated",n=t.format.toUpperCase(),c="[".concat(this.year).concat(this.period,"][").concat(n,"][").concat(r,"] TW-Rental-Data.zip");return"".concat(defs.a).concat(this.year,"/").concat(c)}return""}}},c=(r(554),r(45)),component=Object(c.a)(n,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"dc lh-copy"},[e("div",{staticClass:"dc__title fw5"},[t._v(t._s(t.dataset.type))]),e("div",{staticClass:"dc__count mb2 gray f6"},[t._v("總數： "+t._s(t.dataset.total_count.toLocaleString()))]),t._l(t.dataset.files,(function(r){return e("div",{key:r.format,staticClass:"dc__file"},[e("a",{staticClass:"ttu",attrs:{href:t.downloadUrl(r),target:"_blank",rel:"noopener"}},[t._v("["+t._s(r.format)+"]")])])}))],2)}),[],!1,null,"e1981360",null);e.default=component.exports},564:function(t,e,r){"use strict";r(553)},565:function(t,e,r){var n=r(46)(!1);n.push([t.i,".dbc__fileList[data-v-38962c1c]{display:grid;grid-template-columns:1fr 1fr;grid-column-gap:1rem;-moz-column-gap:1rem;column-gap:1rem}",""]),t.exports=n},574:function(t,e,r){var content=r(593);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("ede6c2f6",content,!0,{sourceMap:!1})},576:function(t,e,r){"use strict";r.r(e);r(16),r(534),r(541),r(291);var n={props:{datasets:{type:Array,required:!0,validator:function(t){return Array.isArray(t)&&t.every((function(t){return t.type&&t.total_count&&t.time&&t.files}))}},year:{type:Number,required:!0},periodPrefix:{type:String,default:"0"},unit:{type:String,default:""}},computed:{period:function(){return this.periodPrefix?this.datasets[0].time.padStart(2,this.periodPrefix):""},comment:function(){var t=this.datasets.find((function(t){return t.comment}));return t?Array.isArray(t)?t:[t]:t}}},c=(r(564),r(45)),component=Object(c.a)(n,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"dbc ba pa3 b--moon-gray"},[e("h3",{staticClass:"mv0 pb3"},[t._v(t._s(t.year)+" "+t._s(t.period)+" "+t._s(t.unit))]),e("div",{staticClass:"dbc__fileList",class:{"ddc__typeList--single":1===t.datasets.length}},t._l(t.datasets,(function(r){return e("dataset-card",{key:r.type,attrs:{dataset:r,year:t.year,period:t.period}})})),1),t.comment?e("div",{staticClass:"dbc__comment pt3"},t._l(t.comment,(function(line){return e("vue-markdown",{key:line,staticClass:"ma0 lh-copy"},[t._v(t._s(line))])})),1):t._e()])}),[],!1,null,"38962c1c",null);e.default=component.exports;installComponents(component,{DatasetCard:r(558).default})},592:function(t,e,r){"use strict";r(574)},593:function(t,e,r){var n=r(46)(!1);n.push([t.i,".index h1[data-v-770f7ced],.index h2[data-v-770f7ced],.index h3[data-v-770f7ced]{font-weight:600}.index__recentPosts[data-v-770f7ced]{background:rgba(158,235,207,.5019607843)}.index__datasetList>div[data-v-770f7ced]:not(:first-child){margin-top:1rem}@media screen and (min-width:60em){.index__datasetList[data-v-770f7ced]{display:grid;grid-template-columns:1fr 1fr 1fr;grid-column-gap:1rem;-moz-column-gap:1rem;column-gap:1rem}.index__datasetList>div[data-v-770f7ced]:not(:first-child){margin:0}}.post[data-v-770f7ced]{text-decoration:none;margin-top:3rem}.post__cover[data-v-770f7ced]{width:100%}.post__cover img[data-v-770f7ced]{-o-object-fit:cover;object-fit:cover}@media screen and (min-width:60em){.post__cover[data-v-770f7ced]{width:25%}}@media screen and (min-width:60em){.post[data-v-770f7ced]:first-child{grid-column:1/span 2}}",""]),t.exports=n},612:function(t,e,r){"use strict";r.r(e);var n=r(13),c=(r(54),r(65),r(567)),o=r(568),d={asyncData:function(t){return Object(n.a)(regeneratorRuntime.mark((function e(){var r,n;return regeneratorRuntime.wrap((function(e){for(;;)switch(e.prev=e.next){case 0:return r=t.$content,e.next=3,r("blog").only(["slug","cover","title","created","excerpt"]).sortBy("created","desc").limit(3).fetch();case 3:return n=e.sent,e.abrupt("return",{recentPosts:n});case 5:case"end":return e.stop()}}),e)})))()},computed:{lastAnnualData:function(){return this.getLastDatasetTuple("annual")},lastQuarterlyData:function(){return this.getLastDatasetTuple("quarterly")},lastMonthlyData:function(){return this.getLastDatasetTuple("monthly")}},methods:{getLastDatasetTuple:function(t){return o[t]&&o[t].length>=2?{year:o.year,datasets:o[t].slice(-2)}:{year:c.year,datasets:c[t].slice(-2)}}}},l=(r(592),r(45)),component=Object(l.a)(d,(function(){var t=this,e=t._self._c;return e("main",{staticClass:"index"},[e("div",{staticClass:"mw7 center pv4 pt5-l pb6-l ph3"},[e("h1",[t._v("開放台灣民間租屋資料")]),e("about-data-brief")],1),e("div",{staticClass:"index__recentPosts pv4 pv6-l ph3"},[e("div",{staticClass:"mw8 center"},[e("h2",{staticClass:"mt0 mb4"},[t._v("近期公告")]),e("div",{staticClass:"index__postList"},t._l(t.recentPosts,(function(r){return e("nuxt-link",{key:r.slug,staticClass:"post flex flex-column-reverse flex-row-l items-center black dim",attrs:{to:"/blog/post/".concat(r.slug,"/")}},[e("div",{staticClass:"flex-auto flex flex-column mt3 mr4-l mt0-l"},[e("h3",{staticClass:"mv0 f4"},[t._v(t._s(r.title))]),e("nuxt-content",{staticClass:"lh-copy",attrs:{document:{body:r.excerpt}}}),e("span",{staticClass:"tr f6 gray"},[e("span",{staticClass:"underline mr1"},[t._v("閱讀更多")]),e("span",[t._v("➡️")])])],1),e("div",{staticClass:"post__cover flex-none"},[e("div",{staticClass:"aspect-ratio aspect-ratio--16x9"},[e("img",{staticClass:"aspect-ratio--object",attrs:{Src:r.cover,alt:r.title}})])])])})),1)])]),e("div",{staticClass:"mw8 center pv4 pv6-l ph3"},[e("h2",{staticClass:"mt0 mb4"},[t._v("最新資料集")]),e("div",{staticClass:"index__datasetList"},[e("dataset-brief-card",{attrs:{year:t.lastAnnualData.year,"period-prefix":"",unit:"年",datasets:t.lastAnnualData.datasets}}),e("dataset-brief-card",{attrs:{year:t.lastQuarterlyData.year,"period-prefix":"Q",unit:"",datasets:t.lastQuarterlyData.datasets}}),e("dataset-brief-card",{attrs:{year:t.lastMonthlyData.year,"period-prefix":"0",unit:"月",datasets:t.lastMonthlyData.datasets}})],1),e("div",{staticClass:"mt3 tr"},[e("nuxt-link",{staticClass:"pa3",attrs:{to:"/download"}},[t._v("查看所有資料集 ➡️")])],1)]),e("twrh-disqus",{staticClass:"mw7 center"})],1)}),[],!1,null,"770f7ced",null);e.default=component.exports;installComponents(component,{AboutDataBrief:r(539).default,DatasetBriefCard:r(576).default,TwrhDisqus:r(536).default})}}]);