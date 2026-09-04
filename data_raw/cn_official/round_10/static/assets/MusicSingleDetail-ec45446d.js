import{d as V,a,m as N,u as R,g as A,w as b,s as Y,t as d,o as m,b as k,e,f as n,h as t,c as B,v as E,j as r,p as w,k as F,r as I,l as M}from"./index-6eea312f.js";import{t as g}from"./numberFormat-0203f5e2.js";import{g as C,a as D,s as U,d as j,G,_ as O}from"./Graph-41af3e26.js";import{g as _}from"./decodeAdditionalConstraint-5d07289b.js";import{_ as Q}from"./Questionnaire.vue_vue_type_script_setup_true_lang-2fa7606f.js";import"./lz-string-0e91bc36.js";import"./Questionnaire-55179045.js";import"./questionnaire-5ec436a8.js";const z={class:"mx-1 my-3"},H={class:"mb-0 md:mx-5 p-3 space-y-3 bg-white bg-opacity-80 rounded-t md:bg-opacity-0 md:rounded md:flex md:flex-wrap md:justify-between md:items-center"},J={class:"flex items-end"},K=e("img",{src:"https://s3c.lilywhite.cc/thvote/imgs/nav/music@100px.png",class:"w-10 h-10 col-span-1 row-span-2 rounded"},null,-1),L={class:"text-4xl font-light"},W=e("span",{class:"ml-3 text-xl"},"曲目信息",-1),X={class:"grid grid-cols-3 md:grid-cols-6 gap-1 text-sm md:text-base text-center"},Z=e("div",null,"票数",-1),ee=e("div",null,"本命票数",-1),te=e("div",null,"本命率",-1),se=e("div",null,"票数全局占比",-1),ae=e("div",null,"本命全局占比",-1),ne=e("div",null,"投票理由",-1),ie={key:1},re=e("div",{class:"md:mx-5 p-3 py-1 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},[r(" * 本页面为单独曲目的详细信息页面，下面每个栏目的内容分别有各自的说明"),e("br")],-1),oe={class:"md:mx-5 p-3"},le=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"投票演进",-1),ue={class:"py-1 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},ce=e("br",null,null,-1),de=e("br",null,null,-1),ve=V({__name:"MusicSingleDetail",setup(me){const i=F(),o=a(Number(i.query.rank?Array.isArray(i.query.rank)?i.query.rank[0]:i.query.rank:1)),l=N(()=>String(i.query.q?Array.isArray(i.query.q)?i.query.q[0]:i.query.q:"")),u=a("ID："+o.value),y=a(-1),p=a(-1),f=a(-1),h=a(-1),q=a(-1),c=a(-1),x=a([]),S=a("NONE"),{result:s,loading:P,onError:$}=R(A`
    query ($voteStart: DateTimeUtc!, $voteYear: Int!, $rank: Int!, $query: String) {
      queryMusicSingle(voteStart: $voteStart, voteYear: $voteYear, rank: $rank, query: $query) {
        name
        voteCount
        firstVoteCount
        firstVotePercentage
        votePercentage
        firstPercentage
        numReasons
        trend {
          hrs
          cnt
        }
        trendFirst {
          hrs
          cnt
        }
      }
    }
  `,_(l.value)===""?{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,rank:o.value}:{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,rank:o.value,query:_(l.value)});return b(()=>{s.value&&s.value.queryMusicSingle&&(u.value=s.value.queryMusicSingle.name,Y(u.value+" - 第⑩回 中文东方人气投票"),S.value='musics:["'+u.value+'"]',y.value=s.value.queryMusicSingle.voteCount,p.value=s.value.queryMusicSingle.firstVoteCount,f.value=g(s.value.queryMusicSingle.firstVotePercentage),h.value=g(s.value.queryMusicSingle.votePercentage),q.value=g(s.value.queryMusicSingle.firstPercentage),c.value=s.value.queryMusicSingle.numReasons,x.value.push(C("总票数",s.value.queryMusicSingle.trend),D("新增票数",s.value.queryMusicSingle.trend),C("总本命票数",s.value.queryMusicSingle.trendFirst),D("新增本命票",s.value.queryMusicSingle.trendFirst)))}),$(v=>{alert(v.message),console.log(v.message)}),b(()=>{P.value?d.isStarted()||d.start():d.isStarted()&&d.done()}),(v,ge)=>{const T=I("router-link");return m(),k("div",z,[e("div",H,[e("div",J,[K,e("h2",L,n(t(u)),1),W]),e("div",X,[e("div",null,[Z,e("div",null,n(t(y)),1)]),e("div",null,[ee,e("div",null,n(t(p)),1)]),e("div",null,[te,e("div",null,n(t(f)),1)]),e("div",null,[se,e("div",null,n(t(h)),1)]),e("div",null,[ae,e("div",null,n(t(q)),1)]),e("div",null,[ne,t(c)>0?(m(),B(T,{key:0,class:"underline",to:"/musicReason?rank="+t(o)+(t(_)(t(l))===""?"":"&q="+t(l))},{default:E(()=>[r(n(t(c)+"(点此查看)"),1)]),_:1},8,["to"])):(m(),k("div",ie,n(t(c)),1))])])]),re,e("div",oe,[le,e("div",ue,[r(" * 该图表表示该曲目随着投票进程的票数变化情况。"),ce,r(" * 投票日期："+n(t(U)+" ~ "+t(j))+"。",1),de,r(" * 通过拖动底部和右侧的滑柄或在图表上缩放（鼠标或手指）可以筛选数据范围，也可以点击顶部的图例开关某个数据的显示。 ")]),w(O,{"x-axis":t(G),data:t(x),class:"max-w-4xl pt-3 mx-auto"},null,8,["x-axis","data"])]),w(Q,{class:"md:mx-5",q:t(S)},null,8,["q"])])}}});typeof M=="function"&&M(ve);export{ve as default};
//# sourceMappingURL=MusicSingleDetail-ec45446d.js.map
