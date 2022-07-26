/*! For license information please see LICENSES */
(window.webpackJsonp=window.webpackJsonp||[]).push([[4,7],{541:function(t,e,n){"use strict";n.r(e);n(16),n(52),n(33),n(35),n(291),n(34),n(187);var r=n(542),o=n.n(r),l=n(545),d=n.n(l),c={beta:"本次資料集有新增欄位，但由於資料更新的限制，並非整個月的的物件都有此資料"},f={props:{rows:{type:Array,required:!0,validator:function(t){return o.a.isArray(t)&&t.every((function(t){return void 0!==t.time&&t.sources&&t.files}))}},idHeader:{type:String,default:""},idFormatter:{type:Function,default:null}},data:function(){return{}},computed:{needIdColumn:function(){return!!this.idHeader},sourceHeaders:function(){return o.a.uniq(o.a.flatten(this.rows.map((function(t){return t.sources.map((function(source){return source.name}))}))))}},methods:{idName:function(t){return this.idFormatter?this.idFormatter(t):t},prettyNumber:function(t){return t.toLocaleString()},prettyTotal:function(t){var e=0;return t.total_count?e=t.total_count:t.sources.forEach((function(source){e+=source.count})),this.prettyNumber(e)},prettyCount:function(t,e){var source=t.sources.find((function(source){return source.name===e}));return source?this.prettyNumber(source.count):"-"},filesize:function(t){return d()(t)},dataUrl:function(t){var e=t.split(" ");return"/about-data-set/".concat(e[0])},dataDesp:function(t){var e=t.split(" ");return e.length>1?c[e[1].toLowerCase()]:""}}},v=n(45),component=Object(v.a)(f,(function(){var t=this,e=t._self._c;return e("table",{staticClass:"download ba b--black-20 w-100 collapse"},[e("tbody",[e("tr",{staticClass:"striped--light-gray"},[t.needIdColumn?e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v(t._s(t.idHeader))]):t._e(),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("內容")]),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("資料集版本")]),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("總物件數")]),t._l(t.sourceHeaders,(function(source){return e("th",{key:source,staticClass:"pv2 ph3 tl f6 fw6"},[t._v(t._s(source)+" 物件數")])})),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("下載連結 / 解壓縮後大小")]),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("附註")])],2),t._l(t.rows,(function(n){return e("tr",{key:n.time+n.type,staticClass:"striped--light-gray"},[t.needIdColumn?e("td",{staticClass:"pv2 ph3"},[t._v(t._s(t.idName(n.time)))]):t._e(),e("td",{staticClass:"pv2 ph3"},[t._v(t._s(n.type))]),e("td",{staticClass:"pv2 ph3"},[e("nuxt-link",{attrs:{to:t.dataUrl(n.data_ver)}},[e("span",{staticClass:"ttu",attrs:{title:t.dataDesp(n.data_ver)}},[t._v(t._s(n.data_ver))])])],1),e("td",{staticClass:"pv2 ph3"},[t._v(t._s(t.prettyTotal(n)))]),t._l(t.sourceHeaders,(function(source){return e("td",{key:source,staticClass:"pv2 ph3"},[t._v(t._s(t.prettyCount(n,source)))])})),e("td",{staticClass:"pv2 ph3"},t._l(n.files,(function(n){return e("div",{key:n.download_url,staticClass:"pv1"},[t._v("["),e("a",{staticClass:"ttu",attrs:{href:n.download_url,target:"_blank",rel:"noopener"}},[t._v(t._s(n.format||"csv")),e("span",{staticClass:"f7 black-50"},[t._v(t._s(t.filesize(n.size_byte)))])]),t._v("]")])})),0),e("td",{staticClass:"pv2 ph3"},[Array.isArray(n.comment)?e("div",t._l(n.comment,(function(line){return e("vue-markdown",{key:line,staticClass:"ma0 lh-copy"},[t._v(t._s(line||"--"))])})),1):e("vue-markdown",[t._v(t._s(n.comment||"--"))])],1)],2)}))],2)])}),[],!1,null,null,null);e.default=component.exports},545:function(t,e,n){"use strict";(function(e){!function(e){var b=/^(b|B)$/,symbol={iec:{bits:["b","Kib","Mib","Gib","Tib","Pib","Eib","Zib","Yib"],bytes:["B","KiB","MiB","GiB","TiB","PiB","EiB","ZiB","YiB"]},jedec:{bits:["b","Kb","Mb","Gb","Tb","Pb","Eb","Zb","Yb"],bytes:["B","KB","MB","GB","TB","PB","EB","ZB","YB"]}},n={iec:["","kibi","mebi","gibi","tebi","pebi","exbi","zebi","yobi"],jedec:["","kilo","mega","giga","tera","peta","exa","zetta","yotta"]};function r(t){var e=arguments.length>1&&void 0!==arguments[1]?arguments[1]:{},r=[],o=0,l=void 0,base=void 0,d=void 0,c=void 0,f=void 0,v=void 0,_=void 0,m=void 0,output=void 0,h=void 0,y=void 0,C=void 0,w=void 0,N=void 0,I=void 0;if(isNaN(t))throw new Error("Invalid arguments");return d=!0===e.bits,y=!0===e.unix,base=e.base||2,h=void 0!==e.round?e.round:y?1:2,C=void 0!==e.separator&&e.separator||"",w=void 0!==e.spacer?e.spacer:y?"":" ",I=e.symbols||e.suffixes||{},N=2===base&&e.standard||"jedec",output=e.output||"string",f=!0===e.fullform,v=e.fullforms instanceof Array?e.fullforms:[],l=void 0!==e.exponent?e.exponent:-1,c=base>2?1e3:1024,(_=(m=Number(t))<0)&&(m=-m),(-1===l||isNaN(l))&&(l=Math.floor(Math.log(m)/Math.log(c)))<0&&(l=0),l>8&&(l=8),0===m?(r[0]=0,r[1]=y?"":symbol[N][d?"bits":"bytes"][l]):(o=m/(2===base?Math.pow(2,10*l):Math.pow(1e3,l)),d&&(o*=8)>=c&&l<8&&(o/=c,l++),r[0]=Number(o.toFixed(l>0?h:0)),r[1]=10===base&&1===l?d?"kb":"kB":symbol[N][d?"bits":"bytes"][l],y&&(r[1]="jedec"===N?r[1].charAt(0):l>0?r[1].replace(/B$/,""):r[1],b.test(r[1])&&(r[0]=Math.floor(r[0]),r[1]=""))),_&&(r[0]=-r[0]),r[1]=I[r[1]]||r[1],"array"===output?r:"exponent"===output?l:"object"===output?{value:r[0],suffix:r[1],symbol:r[1]}:(f&&(r[1]=v[l]?v[l]:n[N][l]+(d?"bit":"byte")+(1===r[0]?"":"s")),C.length>0&&(r[0]=r[0].toString().replace(".",C)),r.join(w))}r.partial=function(t){return function(e){return r(e,t)}},t.exports=r}("undefined"!=typeof window&&window)}).call(this,n(26))},546:function(t,e,n){var content=n(554);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,n(47).default)("4c8b67ab",content,!0,{sourceMap:!1})},551:function(t,e,n){"use strict";var r=n(15),o=n(7),l=n(5),d=n(146),c=n(22),f=n(17),v=n(293),_=n(53),m=n(104),h=n(292),y=n(6),C=n(105).f,w=n(49).f,N=n(21).f,I=n(552),k=n(294).trim,x="Number",B=o.Number,E=B.prototype,T=o.TypeError,M=l("".slice),j=l("".charCodeAt),A=function(t){var e=h(t,"number");return"bigint"==typeof e?e:S(e)},S=function(t){var e,n,r,o,l,d,c,code,f=h(t,"number");if(m(f))throw T("Cannot convert a Symbol value to a number");if("string"==typeof f&&f.length>2)if(f=k(f),43===(e=j(f,0))||45===e){if(88===(n=j(f,2))||120===n)return NaN}else if(48===e){switch(j(f,1)){case 66:case 98:r=2,o=49;break;case 79:case 111:r=8,o=55;break;default:return+f}for(d=(l=M(f,2)).length,c=0;c<d;c++)if((code=j(l,c))<48||code>o)return NaN;return parseInt(l,r)}return+f};if(d(x,!B(" 0o1")||!B("0b1")||B("+0x1"))){for(var F,H=function(t){var e=arguments.length<1?0:B(A(t)),n=this;return _(E,n)&&y((function(){I(n)}))?v(Object(e),n,H):e},O=r?C(B):"MAX_VALUE,MIN_VALUE,NaN,NEGATIVE_INFINITY,POSITIVE_INFINITY,EPSILON,MAX_SAFE_INTEGER,MIN_SAFE_INTEGER,isFinite,isInteger,isNaN,isSafeInteger,parseFloat,parseInt,fromString,range".split(","),D=0;O.length>D;D++)f(B,F=O[D])&&!f(H,F)&&N(H,F,w(B,F));H.prototype=E,E.constructor=H,c(o,x,H,{constructor:!0})}},552:function(t,e,n){var r=n(5);t.exports=r(1..valueOf)},553:function(t,e,n){"use strict";n(546)},554:function(t,e,n){var r=n(46)(!1);r.push([t.i,".seg[data-v-dcf3bdd0]{margin-top:.5rem}.seg[data-v-dcf3bdd0]:not(:last-child){margin-bottom:2rem}.seg>*[data-v-dcf3bdd0]{padding:.5rem 1rem}.seg__title[data-v-dcf3bdd0]{font-size:1.2em;border-bottom:1px solid #000;border-top:1px solid #000}",""]),t.exports=r},560:function(t,e,n){"use strict";n.r(e);n(551);var r={components:{DownloadTable:n(541).default},props:{year:{type:Number,required:!0},definition:{type:Object,required:!0}},data:function(){return{}},computed:{jsonContent:function(){return"data:text/plain;charset=utf-8,"+encodeURIComponent(JSON.stringify(this.definition,null,2))}}},o=(n(553),n(45)),component=Object(o.a)(r,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"annual ba b--black br1 ma4"},[e("div",{staticClass:"annual__header flex justify-between items-center bb b--black bg-black-30"},[e("h2",{staticClass:"ma0 pa2 ml2"},[t._v(t._s(t.year))]),e("div",{staticClass:"pa2 mr2"},[t._v("本表格資料下載 ["),e("a",{attrs:{download:"".concat(t.year,".json"),href:t.jsonContent}},[t._v("JSON")]),t._v("]")])]),t.definition.annual.length?e("div",{staticClass:"annual__seg seg"},[e("div",{staticClass:"seg__title"},[t._v("年度資料")]),e("div",{staticClass:"seg__table"},[e("DownloadTable",{attrs:{idHeader:"年度",rows:t.definition.annual}})],1)]):t._e(),t.definition.quarterly.length?e("div",{staticClass:"annual__seg seg"},[e("div",{staticClass:"seg__title"},[t._v("每季資料")]),e("div",{staticClass:"seg__table"},[e("DownloadTable",{attrs:{idHeader:"季度",rows:t.definition.quarterly}})],1)]):t._e(),e("div",{staticClass:"annual__seg seg"},[e("div",{staticClass:"seg__title"},[t._v("每月資料")]),e("div",{staticClass:"seg__table"},[e("DownloadTable",{attrs:{idHeader:"月份",rows:t.definition.monthly}})],1)])])}),[],!1,null,"dcf3bdd0",null);e.default=component.exports;installComponents(component,{DownloadTable:n(541).default})}}]);