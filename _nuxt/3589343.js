(window.webpackJsonp=window.webpackJsonp||[]).push([[8,9],{534:function(t,e,r){"use strict";var n=r(15),o=r(7),c=r(5),l=r(145),d=r(22),f=r(17),_=r(293),m=r(52),v=r(104),y=r(292),h=r(6),N=r(105).f,w=r(48).f,I=r(21).f,S=r(538),C=r(294).trim,x="Number",A=o.Number,E=A.prototype,M=o.TypeError,k=c("".slice),T=c("".charCodeAt),L=function(t){var e=y(t,"number");return"bigint"==typeof e?e:O(e)},O=function(t){var e,r,n,o,c,l,d,code,f=y(t,"number");if(v(f))throw M("Cannot convert a Symbol value to a number");if("string"==typeof f&&f.length>2)if(f=C(f),43===(e=T(f,0))||45===e){if(88===(r=T(f,2))||120===r)return NaN}else if(48===e){switch(T(f,1)){case 66:case 98:n=2,o=49;break;case 79:case 111:n=8,o=55;break;default:return+f}for(l=(c=k(f,2)).length,d=0;d<l;d++)if((code=T(c,d))<48||code>o)return NaN;return parseInt(c,n)}return+f};if(l(x,!A(" 0o1")||!A("0b1")||A("+0x1"))){for(var F,P=function(t){var e=arguments.length<1?0:A(L(t)),r=this;return m(E,r)&&h((function(){S(r)}))?_(Object(e),r,P):e},U=n?N(A):"MAX_VALUE,MIN_VALUE,NaN,NEGATIVE_INFINITY,POSITIVE_INFINITY,EPSILON,MAX_SAFE_INTEGER,MIN_SAFE_INTEGER,isFinite,isInteger,isNaN,isSafeInteger,parseFloat,parseInt,fromString,range".split(","),V=0;U.length>V;V++)f(A,F=U[V])&&!f(P,F)&&I(P,F,w(A,F));P.prototype=E,E.constructor=P,d(o,x,P,{constructor:!0})}},537:function(t,e,r){"use strict";r.d(e,"a",(function(){return n}));var n="https://tw-rental-data.s3.us-west-2.amazonaws.com/"},538:function(t,e,r){var n=r(5);t.exports=n(1..valueOf)},541:function(t,e,r){"use strict";var n=r(3),o=r(545).start;n({target:"String",proto:!0,forced:r(546)},{padStart:function(t){return o(this,t,arguments.length>1?arguments[1]:void 0)}})},542:function(t,e,r){var content=r(555);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("3a6d37de",content,!0,{sourceMap:!1})},545:function(t,e,r){var n=r(5),o=r(66),c=r(18),l=r(295),d=r(29),f=n(l),_=n("".slice),m=Math.ceil,v=function(t){return function(e,r,n){var l,v,y=c(d(e)),h=o(r),N=y.length,w=void 0===n?" ":c(n);return h<=N||""==w?y:((v=f(w,m((l=h-N)/w.length))).length>l&&(v=_(v,0,l)),t?y+v:v+y)}};t.exports={start:v(!1),end:v(!0)}},546:function(t,e,r){var n=r(84);t.exports=/Version\/10(?:\.\d+){1,2}(?: [\w./]+)?(?: Mobile\/\w+)? Safari\//.test(n)},553:function(t,e,r){var content=r(565);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("2259e751",content,!0,{sourceMap:!1})},554:function(t,e,r){"use strict";r(542)},555:function(t,e,r){var n=r(46)(!1);n.push([t.i,"",""]),t.exports=n},558:function(t,e,r){"use strict";r.r(e);r(534),r(83);var defs=r(537),n={props:{dataset:{type:Object,required:!0},year:{type:Number,required:!0},period:{type:String,required:!0}},methods:{downloadUrl:function(t){console.warn(t);var e=t.download_url;if("string"==typeof e)return e;if(e.isS3){var r="原始資料"===this.dataset.type?"Raw":"Deduplicated",n=t.format.toUpperCase(),o="[".concat(this.year).concat(this.period,"][").concat(n,"][").concat(r,"] TW-Rental-Data.zip");return"".concat(defs.a).concat(this.year,"/").concat(o)}return""}}},o=(r(554),r(45)),component=Object(o.a)(n,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"dc lh-copy"},[e("div",{staticClass:"dc__title fw5"},[t._v(t._s(t.dataset.type))]),e("div",{staticClass:"dc__count mb2 gray f6"},[t._v("總數： "+t._s(t.dataset.total_count.toLocaleString()))]),t._l(t.dataset.files,(function(r){return e("div",{key:r.format,staticClass:"dc__file"},[e("a",{staticClass:"ttu",attrs:{href:t.downloadUrl(r),target:"_blank",rel:"noopener"}},[t._v("["+t._s(r.format)+"]")])])}))],2)}),[],!1,null,"e1981360",null);e.default=component.exports},564:function(t,e,r){"use strict";r(553)},565:function(t,e,r){var n=r(46)(!1);n.push([t.i,".dbc__fileList[data-v-38962c1c]{display:grid;grid-template-columns:1fr 1fr;grid-column-gap:1rem;-moz-column-gap:1rem;column-gap:1rem}",""]),t.exports=n},576:function(t,e,r){"use strict";r.r(e);r(16),r(534),r(541),r(291);var n={props:{datasets:{type:Array,required:!0,validator:function(t){return Array.isArray(t)&&t.every((function(t){return t.type&&t.total_count&&t.time&&t.files}))}},year:{type:Number,required:!0},periodPrefix:{type:String,default:"0"},unit:{type:String,default:""}},computed:{period:function(){return this.periodPrefix?this.datasets[0].time.padStart(2,this.periodPrefix):""},comment:function(){var t=this.datasets.find((function(t){return t.comment}));return t?Array.isArray(t)?t:[t]:t}}},o=(r(564),r(45)),component=Object(o.a)(n,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"dbc ba pa3 b--moon-gray"},[e("h3",{staticClass:"mv0 pb3"},[t._v(t._s(t.year)+" "+t._s(t.period)+" "+t._s(t.unit))]),e("div",{staticClass:"dbc__fileList",class:{"ddc__typeList--single":1===t.datasets.length}},t._l(t.datasets,(function(r){return e("dataset-card",{key:r.type,attrs:{dataset:r,year:t.year,period:t.period}})})),1),t.comment?e("div",{staticClass:"dbc__comment pt3"},t._l(t.comment,(function(line){return e("vue-markdown",{key:line,staticClass:"ma0 lh-copy"},[t._v(t._s(line))])})),1):t._e()])}),[],!1,null,"38962c1c",null);e.default=component.exports;installComponents(component,{DatasetCard:r(558).default})}}]);