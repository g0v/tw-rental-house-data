(window.webpackJsonp=window.webpackJsonp||[]).push([[22,3,7,8,10],{534:function(t,e,o){"use strict";var r=o(15),n=o(7),c=o(5),l=o(145),d=o(22),m=o(17),_=o(293),f=o(52),v=o(104),y=o(292),h=o(6),w=o(105).f,S=o(48).f,z=o(21).f,x=o(538),C=o(294).trim,j="Number",N=n.Number,D=N.prototype,k=n.TypeError,A=c("".slice),I=c("".charCodeAt),L=function(t){var e=y(t,"number");return"bigint"==typeof e?e:M(e)},M=function(t){var e,o,r,n,c,l,d,code,m=y(t,"number");if(v(m))throw k("Cannot convert a Symbol value to a number");if("string"==typeof m&&m.length>2)if(m=C(m),43===(e=I(m,0))||45===e){if(88===(o=I(m,2))||120===o)return NaN}else if(48===e){switch(I(m,1)){case 66:case 98:r=2,n=49;break;case 79:case 111:r=8,n=55;break;default:return+m}for(l=(c=A(m,2)).length,d=0;d<l;d++)if((code=I(c,d))<48||code>n)return NaN;return parseInt(c,r)}return+m};if(l(j,!N(" 0o1")||!N("0b1")||N("+0x1"))){for(var T,E=function(t){var e=arguments.length<1?0:N(L(t)),o=this;return f(D,o)&&h((function(){x(o)}))?_(Object(e),o,E):e},O=r?w(N):"MAX_VALUE,MIN_VALUE,NaN,NEGATIVE_INFINITY,POSITIVE_INFINITY,EPSILON,MAX_SAFE_INTEGER,MIN_SAFE_INTEGER,isFinite,isInteger,isNaN,isSafeInteger,parseFloat,parseInt,fromString,range".split(","),P=0;O.length>P;P++)m(N,T=O[P])&&!m(E,T)&&z(E,T,S(N,T));E.prototype=D,D.constructor=E,d(n,j,E,{constructor:!0})}},535:function(t,e,o){"use strict";o.r(e);var r={data:function(){return{}},computed:{url:function(){return window.location.origin+"/"+this.$route.fullPath}}},n=o(45),component=Object(n.a)(r,(function(){var t=this;return(0,t._self._c)("vue-disqus",{staticClass:"w-100 mt5",attrs:{shortname:"tw-rental-house-data",identifier:t.$route.fullPath,url:t.url}})}),[],!1,null,null,null);e.default=component.exports},536:function(t,e,o){"use strict";o.r(e);var r=o(45),component=Object(r.a)({},(function(){return(0,this._self._c)("vue-markdown",{staticClass:"brief lh-copy",attrs:{breaks:!1,anchorAttributes:{target:"_blank",rel:"noopener"}}},[this._v("「開放民間租屋資料」希望提供對租屋議題有興趣的單位，一份長期、開放，而且詳細的租屋資料集，\n去除有著作權與隱私疑慮的資料後，以\n[CC0](https://creativecommons.org/publicdomain/zero/1.0/deed.zh_TW)\n釋出，為台灣的租賃市場與居住議題建立研究的基礎資料。\n\n本資料集的來源目前為[591 租屋網](https://rent.591.com.tw/)，\n後續也會持續擴充資料來源至各大租屋網與其他代管業者的公開資訊，\n預計每月、每季、每年都會發佈一份該期間內曾經出現過的所有出租物件，\n除了資料標準化外，不做額外的資料處理與刪減，希望盡量保持資料的原始狀態。\n\n本資料集是以現狀提供，並在相關法律容許的最大範圍內，主張免除提供者所有的擔保責任，\n包括但不限於合用性、正確性、權利瑕疵等，使用者並須為其後個案的使用情境自負其責，不得歸咎於提供者。")])}),[],!1,null,null,null);e.default=component.exports},538:function(t,e,o){var r=o(5);t.exports=r(1..valueOf)},539:function(t,e,o){"use strict";o.d(e,"a",(function(){return r}));var r="https://twrh.s3.ap-northeast-3.amazonaws.com/"},540:function(t,e,o){"use strict";var r=o(3),n=o(541).start;r({target:"String",proto:!0,forced:o(542)},{padStart:function(t){return n(this,t,arguments.length>1?arguments[1]:void 0)}})},541:function(t,e,o){var r=o(5),n=o(65),c=o(18),l=o(295),d=o(29),m=r(l),_=r("".slice),f=Math.ceil,v=function(t){return function(e,o,r){var l,v,y=c(d(e)),h=n(o),w=y.length,S=void 0===r?" ":c(r);return h<=w||""==S?y:((v=m(S,f((l=h-w)/S.length))).length>l&&(v=_(v,0,l)),t?y+v:v+y)}};t.exports={start:v(!1),end:v(!0)}},542:function(t,e,o){var r=o(84);t.exports=/Version\/10(?:\.\d+){1,2}(?: [\w./]+)?(?: Mobile\/\w+)? Safari\//.test(r)},544:function(t,e,o){var content=o(555);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,o(47).default)("4d41d9d4",content,!0,{sourceMap:!1})},553:function(t,e,o){var content=o(567);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,o(47).default)("35b14e70",content,!0,{sourceMap:!1})},554:function(t,e,o){"use strict";o(544)},555:function(t,e,o){var r=o(46)(!1);r.push([t.i,"",""]),t.exports=r},558:function(t,e,o){"use strict";o.r(e);o(534),o(83);var defs=o(539),r={props:{dataset:{type:Object,required:!0},year:{type:Number,required:!0},period:{type:String,required:!0}},methods:{downloadUrl:function(t){var e=t.download_url;if("string"==typeof e)return e;if(e.isS3){var o="原始資料"===this.dataset.type?"Raw":"Deduplicated",r=t.format.toUpperCase(),n="[".concat(this.year).concat(this.period,"][").concat(r,"][").concat(o,"] TW-Rental-Data.zip");return"".concat(defs.a).concat(this.year,"/").concat(n)}return""}}},n=(o(554),o(45)),component=Object(n.a)(r,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"dc lh-copy"},[e("div",{staticClass:"dc__title fw5"},[t._v(t._s(t.dataset.type))]),e("div",{staticClass:"dc__count mb2 gray f6"},[t._v("總數： "+t._s(t.dataset.total_count.toLocaleString()))]),t._l(t.dataset.files,(function(o){return e("div",{key:o.format,staticClass:"dc__file"},[e("a",{staticClass:"ttu",attrs:{href:t.downloadUrl(o),target:"_blank",rel:"noopener"}},[t._v("["+t._s(o.format)+"]")])])}))],2)}),[],!1,null,"ae4065a8",null);e.default=component.exports},562:function(t){t.exports=JSON.parse('{"year":2023,"annual":[{"schema_ver":"1.0.0","data_ver":"0.3","time":"1","type":"原始資料","total_count":1501986,"sources":[{"name":"591","count":1501986}],"files":[{"format":"csv","size_byte":654302780,"download_url":{"isS3":true}}],"comment":["爬蟲在 3-4 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)","爬蟲在 10 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-01)"]},{"schema_ver":"1.0.0","data_ver":"0.3","time":"1","type":"消除重複住宅","total_count":1003599,"sources":[{"name":"591","count":1003599}],"files":[{"format":"csv","size_byte":416900306,"download_url":{"isS3":true}}],"comment":["爬蟲在 3-4 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)","爬蟲在 10 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-01)"]}],"quarterly":[{"schema_ver":"1.0.0","data_ver":"0.3","time":"1","type":"原始資料","total_count":374338,"sources":[{"name":"591","count":374338}],"files":[{"format":"csv","size_byte":163104873,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.3","time":"1","type":"消除重複住宅","total_count":261639,"sources":[{"name":"591","count":261639}],"files":[{"format":"csv","size_byte":108256201,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.3","time":"2","type":"原始資料","total_count":438943,"sources":[{"name":"591","count":438943}],"files":[{"format":"csv","size_byte":190934617,"download_url":{"isS3":true}}],"comment":"爬蟲在 3-4 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)"},{"schema_ver":"1.0.0","data_ver":"0.3","time":"2","type":"消除重複住宅","total_count":308702,"sources":[{"name":"591","count":308702}],"files":[{"format":"csv","size_byte":127628256,"download_url":{"isS3":true}}],"comment":"爬蟲在 3-4 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)"},{"schema_ver":"1.0.0","data_ver":"0.3","time":"3","type":"原始資料","total_count":448536,"sources":[{"name":"591","count":448536}],"files":[{"format":"csv","size_byte":194350501,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.3","time":"3","type":"消除重複住宅","total_count":318439,"sources":[{"name":"591","count":318439}],"files":[{"format":"csv","size_byte":131518367,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.3","time":"4","type":"原始資料","total_count":427514,"sources":[{"name":"591","count":427514}],"files":[{"format":"csv","size_byte":185966599,"download_url":{"isS3":true}}],"comment":"爬蟲在 10 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-01)"},{"schema_ver":"1.0.0","data_ver":"0.3","time":"4","type":"消除重複住宅","total_count":322542,"sources":[{"name":"591","count":322542}],"files":[{"format":"csv","size_byte":133753230,"download_url":{"isS3":true}}],"comment":"爬蟲在 10 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-01)"}],"monthly":[{"schema_ver":"1.0.0","data_ver":"0.2","time":"1","type":"原始資料","total_count":146239,"sources":[{"name":"591","count":146239}],"files":[{"format":"csv","size_byte":54791288,"download_url":{"isS3":true}},{"format":"json","size_byte":305641275,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"1","type":"消除重複住宅","total_count":119364,"sources":[{"name":"591","count":119364}],"files":[{"format":"csv","size_byte":42768232,"download_url":{"isS3":true}},{"format":"json","size_byte":248205611,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"2","type":"原始資料","total_count":164852,"sources":[{"name":"591","count":164852}],"files":[{"format":"csv","size_byte":61928563,"download_url":{"isS3":true}},{"format":"json","size_byte":344673555,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"2","type":"消除重複住宅","total_count":135122,"sources":[{"name":"591","count":135122}],"files":[{"format":"csv","size_byte":48531049,"download_url":{"isS3":true}},{"format":"json","size_byte":281070306,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"3","type":"原始資料","total_count":174120,"sources":[{"name":"591","count":174120}],"files":[{"format":"csv","size_byte":65385385,"download_url":{"isS3":true}},{"format":"json","size_byte":364043115,"download_url":{"isS3":true}}],"comment":"爬蟲在 3 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)"},{"schema_ver":"1.0.0","data_ver":"0.2","time":"3","type":"消除重複住宅","total_count":141925,"sources":[{"name":"591","count":141925}],"files":[{"format":"csv","size_byte":50935216,"download_url":{"isS3":true}},{"format":"json","size_byte":295196245,"download_url":{"isS3":true}}],"comment":"爬蟲在 3 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)"},{"schema_ver":"1.0.0","data_ver":"0.2","time":"4","type":"原始資料","total_count":181193,"sources":[{"name":"591","count":181193}],"files":[{"format":"csv","size_byte":67630485,"download_url":{"isS3":true}},{"format":"json","size_byte":378477097,"download_url":{"isS3":true}}],"comment":"爬蟲在 4 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)"},{"schema_ver":"1.0.0","data_ver":"0.2","time":"4","type":"消除重複住宅","total_count":150881,"sources":[{"name":"591","count":150881}],"files":[{"format":"csv","size_byte":53894295,"download_url":{"isS3":true}},{"format":"json","size_byte":313599510,"download_url":{"isS3":true}}],"comment":"爬蟲在 4 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-00)"},{"schema_ver":"1.0.0","data_ver":"0.2","time":"5","type":"原始資料","total_count":197599,"sources":[{"name":"591","count":197599}],"files":[{"format":"csv","size_byte":74305330,"download_url":{"isS3":true}},{"format":"json","size_byte":413220556,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"5","type":"消除重複住宅","total_count":157663,"sources":[{"name":"591","count":157663}],"files":[{"format":"csv","size_byte":56694345,"download_url":{"isS3":true}},{"format":"json","size_byte":328027713,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"6","type":"原始資料","total_count":185605,"sources":[{"name":"591","count":185605}],"files":[{"format":"csv","size_byte":69693935,"download_url":{"isS3":true}},{"format":"json","size_byte":388059630,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"6","type":"消除重複住宅","total_count":151460,"sources":[{"name":"591","count":151460}],"files":[{"format":"csv","size_byte":54421438,"download_url":{"isS3":true}},{"format":"json","size_byte":315091976,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"7","type":"原始資料","total_count":191276,"sources":[{"name":"591","count":191276}],"files":[{"format":"csv","size_byte":71495613,"download_url":{"isS3":true}},{"format":"json","size_byte":399629920,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"7","type":"消除重複住宅","total_count":156195,"sources":[{"name":"591","count":156195}],"files":[{"format":"csv","size_byte":55960994,"download_url":{"isS3":true}},{"format":"json","size_byte":324800746,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"8","type":"原始資料","total_count":194940,"sources":[{"name":"591","count":194940}],"files":[{"format":"csv","size_byte":72870650,"download_url":{"isS3":true}},{"format":"json","size_byte":407277466,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"8","type":"消除重複住宅","total_count":160012,"sources":[{"name":"591","count":160012}],"files":[{"format":"csv","size_byte":57387726,"download_url":{"isS3":true}},{"format":"json","size_byte":332783125,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"9","type":"原始資料","total_count":184585,"sources":[{"name":"591","count":184585}],"files":[{"format":"csv","size_byte":69048552,"download_url":{"isS3":true}},{"format":"json","size_byte":385658648,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"9","type":"消除重複住宅","total_count":152100,"sources":[{"name":"591","count":152100}],"files":[{"format":"csv","size_byte":54555038,"download_url":{"isS3":true}},{"format":"json","size_byte":316310019,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"10","type":"原始資料","total_count":171122,"sources":[{"name":"591","count":171122}],"files":[{"format":"csv","size_byte":63983854,"download_url":{"isS3":true}},{"format":"json","size_byte":357495685,"download_url":{"isS3":true}}],"comment":"爬蟲在 10 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-01)"},{"schema_ver":"1.0.0","data_ver":"0.2","time":"10","type":"消除重複住宅","total_count":146992,"sources":[{"name":"591","count":146992}],"files":[{"format":"csv","size_byte":52708606,"download_url":{"isS3":true}},{"format":"json","size_byte":305659843,"download_url":{"isS3":true}}],"comment":"爬蟲在 10 月曾出現資料錯誤，將會影響部份物件的新增與更新日期，詳細資訊請參見[部落格](/blog/post/data-issue-2023-01)"},{"schema_ver":"1.0.0","data_ver":"0.2","time":"11","type":"原始資料","total_count":190215,"sources":[{"name":"591","count":190215}],"files":[{"format":"csv","size_byte":71459992,"download_url":{"isS3":true}},{"format":"json","size_byte":397675273,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"11","type":"消除重複住宅","total_count":153405,"sources":[{"name":"591","count":153405}],"files":[{"format":"csv","size_byte":55273104,"download_url":{"isS3":true}},{"format":"json","size_byte":319232964,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"12","type":"原始資料","total_count":197126,"sources":[{"name":"591","count":197126}],"files":[{"format":"csv","size_byte":74175207,"download_url":{"isS3":true}},{"format":"json","size_byte":412202367,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"12","type":"消除重複住宅","total_count":151950,"sources":[{"name":"591","count":151950}],"files":[{"format":"csv","size_byte":54785172,"download_url":{"isS3":true}},{"format":"json","size_byte":316207681,"download_url":{"isS3":true}}],"comment":""}]}')},563:function(t){t.exports=JSON.parse('{"year":2024,"annual":[],"quarterly":[],"monthly":[{"schema_ver":"1.0.0","data_ver":"0.2","time":"1","type":"原始資料","total_count":192990,"sources":[{"name":"591","count":192990}],"files":[{"format":"csv","size_byte":73630870,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"1","type":"消除重複住宅","total_count":151691,"sources":[{"name":"591","count":151691}],"files":[{"format":"csv","size_byte":63649919,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"2","type":"原始資料","total_count":174448,"sources":[{"name":"591","count":174448}],"files":[{"format":"csv","size_byte":66386779,"download_url":{"isS3":true}}],"comment":""},{"schema_ver":"1.0.0","data_ver":"0.2","time":"2","type":"消除重複住宅","total_count":136424,"sources":[{"name":"591","count":136424}],"files":[{"format":"csv","size_byte":57076371,"download_url":{"isS3":true}}],"comment":""}]}')},566:function(t,e,o){"use strict";o(553)},567:function(t,e,o){var r=o(46)(!1);r.push([t.i,".dbc__fileList[data-v-9f46eefa]{display:grid;grid-template-columns:1fr 1fr;grid-column-gap:1rem;-moz-column-gap:1rem;column-gap:1rem}",""]),t.exports=r},575:function(t,e,o){var content=o(598);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,o(47).default)("6dfda01b",content,!0,{sourceMap:!1})},577:function(t,e,o){"use strict";o.r(e);o(16),o(534),o(540),o(291);var r={props:{datasets:{type:Array,required:!0,validator:function(t){return Array.isArray(t)&&t.every((function(t){return t.type&&t.total_count&&t.time&&t.files}))}},year:{type:Number,required:!0},periodPrefix:{type:String,default:"0"},unit:{type:String,default:""}},computed:{period:function(){return this.periodPrefix?this.datasets[0].time.padStart(2,this.periodPrefix):""},comment:function(){var t=this.datasets.find((function(t){return t.comment}));return t?Array.isArray(t.comment)?t.comment:[t.comment]:t}}},n=(o(566),o(45)),component=Object(n.a)(r,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"dbc ba pa3 b--moon-gray"},[e("h3",{staticClass:"mv0 pb3"},[t._v(t._s(t.year)+" "+t._s(t.period)+" "+t._s(t.unit))]),e("div",{staticClass:"dbc__fileList",class:{"ddc__typeList--single":1===t.datasets.length}},t._l(t.datasets,(function(o){return e("dataset-card",{key:o.type,attrs:{dataset:o,year:t.year,period:t.period}})})),1),t.comment?e("div",{staticClass:"dbc__comment pt3"},t._l(t.comment,(function(line){return e("vue-markdown",{key:line,staticClass:"ma0 lh-copy"},[t._v(t._s(line))])})),1):t._e()])}),[],!1,null,"9f46eefa",null);e.default=component.exports;installComponents(component,{DatasetCard:o(558).default})},597:function(t,e,o){"use strict";o(575)},598:function(t,e,o){var r=o(46)(!1);r.push([t.i,".index h1[data-v-219cf21e],.index h2[data-v-219cf21e],.index h3[data-v-219cf21e]{font-weight:600}.index__recentPosts[data-v-219cf21e]{background:rgba(158,235,207,.5019607843)}.index__datasetList>div[data-v-219cf21e]:not(:first-child){margin-top:1rem}@media screen and (min-width:60em){.index__datasetList[data-v-219cf21e]{display:grid;grid-template-columns:1fr 1fr 1fr;grid-column-gap:1rem;-moz-column-gap:1rem;column-gap:1rem}.index__datasetList>div[data-v-219cf21e]:not(:first-child){margin:0}}.post[data-v-219cf21e]{text-decoration:none;margin-top:3rem}.post__cover[data-v-219cf21e]{width:100%}.post__cover img[data-v-219cf21e]{-o-object-fit:cover;object-fit:cover}@media screen and (min-width:60em){.post__cover[data-v-219cf21e]{width:25%}}@media screen and (min-width:60em){.post[data-v-219cf21e]:first-child{grid-column:1/span 2}}",""]),t.exports=r},618:function(t,e,o){"use strict";o.r(e);var r=o(13),n=(o(54),o(66),o(562)),c=o(563),l={asyncData:function(t){return Object(r.a)(regeneratorRuntime.mark((function e(){var o,r;return regeneratorRuntime.wrap((function(e){for(;;)switch(e.prev=e.next){case 0:return o=t.$content,e.next=3,o("blog").only(["slug","cover","title","created","excerpt"]).sortBy("created","desc").limit(3).fetch();case 3:return r=e.sent,e.abrupt("return",{recentPosts:r});case 5:case"end":return e.stop()}}),e)})))()},computed:{lastAnnualData:function(){return this.getLastDatasetTuple("annual")},lastQuarterlyData:function(){return this.getLastDatasetTuple("quarterly")},lastMonthlyData:function(){return this.getLastDatasetTuple("monthly")}},methods:{getLastDatasetTuple:function(t){return c[t]&&c[t].length>=2?{year:c.year,datasets:c[t].slice(-2)}:{year:n.year,datasets:n[t].slice(-2)}}}},d=(o(597),o(45)),component=Object(d.a)(l,(function(){var t=this,e=t._self._c;return e("main",{staticClass:"index"},[e("div",{staticClass:"mw7 center pv4 pt5-l pb6-l ph3"},[e("h1",[t._v("開放台灣民間租屋資料")]),e("about-data-brief")],1),e("div",{staticClass:"index__recentPosts pv4 pv6-l ph3"},[e("div",{staticClass:"mw8 center"},[e("h2",{staticClass:"mt0 mb4"},[t._v("近期公告")]),e("div",{staticClass:"index__postList"},t._l(t.recentPosts,(function(o){return e("nuxt-link",{key:o.slug,staticClass:"post flex flex-column-reverse flex-row-l items-center black dim",attrs:{to:"/blog/post/".concat(o.slug,"/")}},[e("div",{staticClass:"flex-auto flex flex-column mt3 mr4-l mt0-l"},[e("h3",{staticClass:"mv0 f4"},[t._v(t._s(o.title))]),e("nuxt-content",{staticClass:"lh-copy",attrs:{document:{body:o.excerpt}}}),e("span",{staticClass:"tr f6 gray"},[e("span",{staticClass:"underline mr1"},[t._v("閱讀更多")]),e("span",[t._v("➡️")])])],1),e("div",{staticClass:"post__cover flex-none"},[e("div",{staticClass:"aspect-ratio aspect-ratio--16x9"},[e("img",{staticClass:"aspect-ratio--object",attrs:{Src:o.cover,alt:o.title}})])])])})),1)])]),e("div",{staticClass:"mw8 center pv4 pv6-l ph3"},[e("h2",{staticClass:"mt0 mb4"},[t._v("最新資料集")]),e("div",{staticClass:"index__datasetList"},[e("dataset-brief-card",{attrs:{year:t.lastAnnualData.year,"period-prefix":"",unit:"年",datasets:t.lastAnnualData.datasets}}),e("dataset-brief-card",{attrs:{year:t.lastQuarterlyData.year,"period-prefix":"Q",unit:"",datasets:t.lastQuarterlyData.datasets}}),e("dataset-brief-card",{attrs:{year:t.lastMonthlyData.year,"period-prefix":"0",unit:"月",datasets:t.lastMonthlyData.datasets}})],1),e("div",{staticClass:"mt3 tr"},[e("nuxt-link",{staticClass:"pa3",attrs:{to:"/download"}},[t._v("查看所有資料集 ➡️")])],1)]),e("twrh-disqus",{staticClass:"mw7 center"})],1)}),[],!1,null,"219cf21e",null);e.default=component.exports;installComponents(component,{AboutDataBrief:o(536).default,DatasetBriefCard:o(577).default,TwrhDisqus:o(535).default})}}]);