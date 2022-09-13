/*! For license information please see LICENSES */
(window.webpackJsonp=window.webpackJsonp||[]).push([[7],{540:function(t,e,r){"use strict";var n=r(15),o=r(7),c=r(5),l=r(146),f=r(22),d=r(17),v=r(293),h=r(53),m=r(104),_=r(292),y=r(6),w=r(105).f,N=r(49).f,C=r(21).f,I=r(545),B=r(295).trim,k="Number",E=o.Number,x=E.prototype,M=o.TypeError,S=c("".slice),A=c("".charCodeAt),T=function(t){var e=_(t,"number");return"bigint"==typeof e?e:F(e)},F=function(t){var e,r,n,o,c,l,f,code,d=_(t,"number");if(m(d))throw M("Cannot convert a Symbol value to a number");if("string"==typeof d&&d.length>2)if(d=B(d),43===(e=A(d,0))||45===e){if(88===(r=A(d,2))||120===r)return NaN}else if(48===e){switch(A(d,1)){case 66:case 98:n=2,o=49;break;case 79:case 111:n=8,o=55;break;default:return+d}for(l=(c=S(d,2)).length,f=0;f<l;f++)if((code=A(c,f))<48||code>o)return NaN;return parseInt(c,n)}return+d};if(l(k,!E(" 0o1")||!E("0b1")||E("+0x1"))){for(var j,P=function(t){var e=arguments.length<1?0:E(T(t)),r=this;return h(x,r)&&y((function(){I(r)}))?v(Object(e),r,P):e},z=n?w(E):"MAX_VALUE,MIN_VALUE,NaN,NEGATIVE_INFINITY,POSITIVE_INFINITY,EPSILON,MAX_SAFE_INTEGER,MIN_SAFE_INTEGER,isFinite,isInteger,isNaN,isSafeInteger,parseFloat,parseInt,fromString,range".split(","),G=0;z.length>G;G++)d(E,j=z[G])&&!d(P,j)&&C(P,j,N(E,j));P.prototype=x,x.constructor=P,f(o,k,P,{constructor:!0})}},545:function(t,e,r){var n=r(5);t.exports=n(1..valueOf)},547:function(t,e,r){"use strict";var n=r(3),o=r(548).start;n({target:"String",proto:!0,forced:r(549)},{padStart:function(t){return o(this,t,arguments.length>1?arguments[1]:void 0)}})},548:function(t,e,r){var n=r(5),o=r(66),c=r(18),l=r(294),f=r(29),d=n(l),v=n("".slice),h=Math.ceil,m=function(t){return function(e,r,n){var l,m,_=c(f(e)),y=o(r),w=_.length,N=void 0===n?" ":c(n);return y<=w||""==N?_:((m=d(N,h((l=y-w)/N.length))).length>l&&(m=v(m,0,l)),t?_+m:m+_)}};t.exports={start:m(!1),end:m(!0)}},549:function(t,e,r){var n=r(83);t.exports=/Version\/10(?:\.\d+){1,2}(?: [\w./]+)?(?: Mobile\/\w+)? Safari\//.test(n)},550:function(t,e,r){"use strict";(function(e){!function(e){var b=/^(b|B)$/,symbol={iec:{bits:["b","Kib","Mib","Gib","Tib","Pib","Eib","Zib","Yib"],bytes:["B","KiB","MiB","GiB","TiB","PiB","EiB","ZiB","YiB"]},jedec:{bits:["b","Kb","Mb","Gb","Tb","Pb","Eb","Zb","Yb"],bytes:["B","KB","MB","GB","TB","PB","EB","ZB","YB"]}},r={iec:["","kibi","mebi","gibi","tebi","pebi","exbi","zebi","yobi"],jedec:["","kilo","mega","giga","tera","peta","exa","zetta","yotta"]};function n(t){var e=arguments.length>1&&void 0!==arguments[1]?arguments[1]:{},n=[],o=0,c=void 0,base=void 0,l=void 0,f=void 0,d=void 0,v=void 0,h=void 0,m=void 0,output=void 0,_=void 0,y=void 0,w=void 0,N=void 0,C=void 0,I=void 0;if(isNaN(t))throw new Error("Invalid arguments");return l=!0===e.bits,y=!0===e.unix,base=e.base||2,_=void 0!==e.round?e.round:y?1:2,w=void 0!==e.separator&&e.separator||"",N=void 0!==e.spacer?e.spacer:y?"":" ",I=e.symbols||e.suffixes||{},C=2===base&&e.standard||"jedec",output=e.output||"string",d=!0===e.fullform,v=e.fullforms instanceof Array?e.fullforms:[],c=void 0!==e.exponent?e.exponent:-1,f=base>2?1e3:1024,(h=(m=Number(t))<0)&&(m=-m),(-1===c||isNaN(c))&&(c=Math.floor(Math.log(m)/Math.log(f)))<0&&(c=0),c>8&&(c=8),0===m?(n[0]=0,n[1]=y?"":symbol[C][l?"bits":"bytes"][c]):(o=m/(2===base?Math.pow(2,10*c):Math.pow(1e3,c)),l&&(o*=8)>=f&&c<8&&(o/=f,c++),n[0]=Number(o.toFixed(c>0?_:0)),n[1]=10===base&&1===c?l?"kb":"kB":symbol[C][l?"bits":"bytes"][c],y&&(n[1]="jedec"===C?n[1].charAt(0):c>0?n[1].replace(/B$/,""):n[1],b.test(n[1])&&(n[0]=Math.floor(n[0]),n[1]=""))),h&&(n[0]=-n[0]),n[1]=I[n[1]]||n[1],"array"===output?n:"exponent"===output?c:"object"===output?{value:n[0],suffix:n[1],symbol:n[1]}:(d&&(n[1]=v[c]?v[c]:r[C][c]+(l?"bit":"byte")+(1===n[0]?"":"s")),w.length>0&&(n[0]=n[0].toString().replace(".",w)),n.join(N))}n.partial=function(t){return function(e){return n(e,t)}},t.exports=n}("undefined"!=typeof window&&window)}).call(this,r(26))},552:function(t,e,r){"use strict";r.r(e);r(540),r(16),r(52),r(33),r(35),r(291),r(34),r(187),r(547),r(84);var n=r(542),o=r.n(n),c=r(550),l=r.n(c),f={beta:"本次資料集有新增欄位，但由於資料更新的限制，並非整個月的的物件都有此資料"},d={props:{year:{type:Number,required:!0},rows:{type:Array,required:!0,validator:function(t){return o.a.isArray(t)&&t.every((function(t){return void 0!==t.time&&t.sources&&t.files}))}},idHeader:{type:String,default:""},idFormatter:{type:Function,default:null},periodPrefix:{type:String,default:"0"}},data:function(){return{}},computed:{needIdColumn:function(){return!!this.idHeader},sourceHeaders:function(){return o.a.uniq(o.a.flatten(this.rows.map((function(t){return t.sources.map((function(source){return source.name}))}))))}},methods:{idName:function(t){return this.idFormatter?this.idFormatter(t):t},prettyNumber:function(t){return t.toLocaleString()},prettyTotal:function(t){var e=0;return t.total_count?e=t.total_count:t.sources.forEach((function(source){e+=source.count})),this.prettyNumber(e)},prettyCount:function(t,e){var source=t.sources.find((function(source){return source.name===e}));return source?this.prettyNumber(source.count):"-"},filesize:function(t){return l()(t)},dataUrl:function(t){var e=t.split(" ");return"/about-data-set/".concat(e[0])},dataDesp:function(t){var e=t.split(" ");return e.length>1?f[e[1].toLowerCase()]:""},downloadUrl:function(t,e){var r=t.download_url;if("string"==typeof r)return r;if(r.isS3){var n=e.time.padStart(2,this.periodPrefix),o="原始資料"===e.type?"Raw":"Deduplicated",c=t.format.toUpperCase(),l="[".concat(this.year).concat(n,"][").concat(c,"][").concat(o,"] TW-Rental-Data.zip");return"".concat("https://tw-rental-data.s3.us-west-2.amazonaws.com/").concat(l)}return""}}},v=r(45),component=Object(v.a)(d,(function(){var t=this,e=t._self._c;return e("table",{staticClass:"download ba b--black-20 w-100 collapse"},[e("tbody",[e("tr",{staticClass:"striped--light-gray"},[t.needIdColumn?e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v(t._s(t.idHeader))]):t._e(),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("內容")]),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("資料集版本")]),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("總物件數")]),t._l(t.sourceHeaders,(function(source){return e("th",{key:source,staticClass:"pv2 ph3 tl f6 fw6"},[t._v(t._s(source)+" 物件數")])})),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("下載連結 / 解壓縮後大小")]),e("th",{staticClass:"pv2 ph3 tl f6 fw6"},[t._v("附註")])],2),t._l(t.rows,(function(r){return e("tr",{key:r.time+r.type,staticClass:"striped--light-gray"},[t.needIdColumn?e("td",{staticClass:"pv2 ph3"},[t._v(t._s(t.idName(r.time)))]):t._e(),e("td",{staticClass:"pv2 ph3"},[t._v(t._s(r.type))]),e("td",{staticClass:"pv2 ph3"},[e("nuxt-link",{attrs:{to:t.dataUrl(r.data_ver)}},[e("span",{staticClass:"ttu",attrs:{title:t.dataDesp(r.data_ver)}},[t._v(t._s(r.data_ver))])])],1),e("td",{staticClass:"pv2 ph3"},[t._v(t._s(t.prettyTotal(r)))]),t._l(t.sourceHeaders,(function(source){return e("td",{key:source,staticClass:"pv2 ph3"},[t._v(t._s(t.prettyCount(r,source)))])})),e("td",{staticClass:"pv2 ph3"},t._l(r.files,(function(n){return e("div",{key:n.format,staticClass:"pv1"},[t._v("["),e("a",{staticClass:"ttu",attrs:{href:t.downloadUrl(n,r),target:"_blank",rel:"noopener"}},[t._v(t._s(n.format||"csv")),e("span",{staticClass:"f7 black-50"},[t._v(t._s(t.filesize(n.size_byte)))])]),t._v("]")])})),0),e("td",{staticClass:"pv2 ph3"},[Array.isArray(r.comment)?e("div",t._l(r.comment,(function(line){return e("vue-markdown",{key:line,staticClass:"ma0 lh-copy"},[t._v(t._s(line||"--"))])})),1):e("vue-markdown",[t._v(t._s(r.comment||"--"))])],1)],2)}))],2)])}),[],!1,null,null,null);e.default=component.exports}}]);