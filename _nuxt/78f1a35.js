(window.webpackJsonp=window.webpackJsonp||[]).push([[8],{534:function(t,e,r){"use strict";var n=r(15),o=r(7),c=r(5),f=r(145),l=r(22),d=r(17),_=r(293),v=r(52),N=r(104),h=r(292),y=r(6),I=r(105).f,m=r(48).f,w=r(21).f,E=r(537),S=r(294).trim,A="Number",C=o.Number,T=C.prototype,k=o.TypeError,F=c("".slice),M=c("".charCodeAt),O=function(t){var e=h(t,"number");return"bigint"==typeof e?e:x(e)},x=function(t){var e,r,n,o,c,f,l,code,d=h(t,"number");if(N(d))throw k("Cannot convert a Symbol value to a number");if("string"==typeof d&&d.length>2)if(d=S(d),43===(e=M(d,0))||45===e){if(88===(r=M(d,2))||120===r)return NaN}else if(48===e){switch(M(d,1)){case 66:case 98:n=2,o=49;break;case 79:case 111:n=8,o=55;break;default:return+d}for(f=(c=F(d,2)).length,l=0;l<f;l++)if((code=M(c,l))<48||code>o)return NaN;return parseInt(c,n)}return+d};if(f(A,!C(" 0o1")||!C("0b1")||C("+0x1"))){for(var U,L=function(t){var e=arguments.length<1?0:C(O(t)),r=this;return v(T,r)&&y((function(){E(r)}))?_(Object(e),r,L):e},R=n?I(C):"MAX_VALUE,MIN_VALUE,NaN,NEGATIVE_INFINITY,POSITIVE_INFINITY,EPSILON,MAX_SAFE_INTEGER,MIN_SAFE_INTEGER,isFinite,isInteger,isNaN,isSafeInteger,parseFloat,parseInt,fromString,range".split(","),V=0;R.length>V;V++)d(C,U=R[V])&&!d(L,U)&&w(L,U,m(C,U));L.prototype=T,T.constructor=L,l(o,A,L,{constructor:!0})}},537:function(t,e,r){var n=r(5);t.exports=n(1..valueOf)},538:function(t,e,r){"use strict";r.d(e,"a",(function(){return n}));var n="https://tw-rental-data.s3.us-west-2.amazonaws.com/"},544:function(t,e,r){var content=r(555);content.__esModule&&(content=content.default),"string"==typeof content&&(content=[[t.i,content,""]]),content.locals&&(t.exports=content.locals);(0,r(47).default)("4d41d9d4",content,!0,{sourceMap:!1})},554:function(t,e,r){"use strict";r(544)},555:function(t,e,r){var n=r(46)(!1);n.push([t.i,"",""]),t.exports=n},558:function(t,e,r){"use strict";r.r(e);r(534),r(83);var defs=r(538),n={props:{dataset:{type:Object,required:!0},year:{type:Number,required:!0},period:{type:String,required:!0}},methods:{downloadUrl:function(t){var e=t.download_url;if("string"==typeof e)return e;if(e.isS3){var r="原始資料"===this.dataset.type?"Raw":"Deduplicated",n=t.format.toUpperCase(),o="[".concat(this.year).concat(this.period,"][").concat(n,"][").concat(r,"] TW-Rental-Data.zip");return"".concat(defs.a).concat(this.year,"/").concat(o)}return""}}},o=(r(554),r(45)),component=Object(o.a)(n,(function(){var t=this,e=t._self._c;return e("div",{staticClass:"dc lh-copy"},[e("div",{staticClass:"dc__title fw5"},[t._v(t._s(t.dataset.type))]),e("div",{staticClass:"dc__count mb2 gray f6"},[t._v("總數： "+t._s(t.dataset.total_count.toLocaleString()))]),t._l(t.dataset.files,(function(r){return e("div",{key:r.format,staticClass:"dc__file"},[e("a",{staticClass:"ttu",attrs:{href:t.downloadUrl(r),target:"_blank",rel:"noopener"}},[t._v("["+t._s(r.format)+"]")])])}))],2)}),[],!1,null,"ae4065a8",null);e.default=component.exports}}]);