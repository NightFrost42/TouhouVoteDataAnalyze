import{d as N,a as l,m as f,u as U,g as j,w as D,t as k,s as O,o as r,b as o,e,f as a,h as s,F as g,i as m,y as z,c as L,v as M,j as C,k as Q,r as W,l as Y}from"./index-6eea312f.js";import{t as y}from"./numberFormat-0203f5e2.js";import{g as F}from"./decodeAdditionalConstraint-5d07289b.js";import"./lz-string-0e91bc36.js";const G={class:"mx-1 my-3"},H={class:"mb-0 md:mx-5 p-3 space-y-3 bg-white bg-opacity-80 rounded-t md:bg-opacity-0 md:rounded md:flex md:flex-wrap md:justify-between md:items-center"},J={class:"flex items-center"},K=e("img",{src:"https://s3c.lilywhite.cc/thvote/imgs/nav/couple@100px.png",class:"w-10 h-10 col-span-1 row-span-2 rounded"},null,-1),X=e("h2",{class:"text-3xl font-light"},"投票理由",-1),Z={class:"text-xl hidden md:inline-block"},ee={class:"text-xl md:hidden"},te={class:"grid grid-cols-3 md:grid-cols-6 gap-1 text-sm md:text-base text-center"},ne=e("div",null,"票数",-1),ae=e("div",null,"本命票数",-1),re=e("div",null,"本命率",-1),se=e("div",null,"票数全局占比",-1),oe=e("div",null,"本命全局占比",-1),ie=e("div",null,"理由数量",-1),le=e("div",{class:"md:mx-5 p-3 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},[C(" * 本页面列出所有投票的时候用户提交的投票理由"),e("br"),C(" * 可使用 Ctrl + F 或 ⌘ + F 调出浏览器自带的搜索功能进行搜索 ")],-1),ce={class:"md:mx-5 p-3"},ue=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"角色与主动方倾向信息信息",-1),de={class:"flex bg-white"},ve={class:"flex-grow flex"},ye={class:"p-1 whitespace-nowrap border-b border-accent-600"},ge={key:1,class:"p-1 truncate max-w-30 md:max-w-none"},me={class:"flex flex-nowrap overflow-auto"},pe={class:"p-1 whitespace-nowrap border-b border-accent-600"},_e={class:"p-1 truncate max-w-30 md:max-w-none"},ke={class:"md:mx-5 p-3 divide-y-1 divide-accent-300"},he=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"理由列表",-1),fe=N({__name:"CoupleReason",setup(Ce){const c=Q(),h=l(Number(c.query.rank?Array.isArray(c.query.rank)?c.query.rank[0]:c.query.rank:1)),x=f(()=>String(c.query.q?Array.isArray(c.query.q)?c.query.q[0]:c.query.q:"")),p=l("ID："+h.value),q=l(-1),b=l(-1),S=l(-1),P=l(-1),w=l(-1),R=l([]),V=l(-1),{result:t,loading:E,onError:I}=U(j`
    query ($voteStart: DateTimeUtc!, $voteYear: Int!, $rank: Int!, $query: String) {
      queryCPSingle(voteStart: $voteStart, voteYear: $voteYear, rank: $rank, query: $query) {
        cp {
          a
          b
          c
        }
        aActive
        bActive
        cActive
        noneActive
        voteCount
        firstVoteCount
        firstVotePercentage
        votePercentage
        firstPercentage
        reasons
        numReasons
      }
      queryCharacterRanking(voteStart: $voteStart, voteYear: $voteYear) {
        entries {
          rank
          displayRank
          name
          voteCount
          firstVoteCount
          firstVotePercentage
        }
      }
    }
  `,F(x.value)===""?{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,rank:h.value}:{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,rank:h.value,query:F(x.value)});D(()=>{E.value?k.isStarted()||k.start():k.isStarted()&&k.done()}),D(()=>{if(t.value&&(t.value.queryCPSingle&&(p.value=t.value.queryCPSingle.cp.a+" x "+t.value.queryCPSingle.cp.b+(t.value.queryCPSingle.cp.c?" x "+t.value.queryCPSingle.cp.c:""),O(p.value+" - 第⑩回 中文东方人气投票"),q.value=t.value.queryCPSingle.voteCount,b.value=t.value.queryCPSingle.firstVoteCount,S.value=y(t.value.queryCPSingle.firstVotePercentage),P.value=y(t.value.queryCPSingle.votePercentage),w.value=y(t.value.queryCPSingle.firstPercentage),R.value=t.value.queryCPSingle.reasons,V.value=t.value.queryCPSingle.numReasons),t.value.queryCharacterRanking.entries&&t.value.queryCPSingle)){const d=["a","b","c"];for(const v of d){const u=t.value.queryCharacterRanking.entries.findIndex(i=>{var $;return i.name===((($=t.value)==null?void 0:$.queryCPSingle.cp[v])||"ERROR")});if(u===-1)continue;const n=v+"Active";_.value.push({rank:t.value.queryCharacterRanking.entries[u].rank,name:t.value.queryCPSingle.cp[v]||"ERROR",active:y(t.value.queryCPSingle[n]),displayRank:t.value.queryCharacterRanking.entries[u].displayRank,voteCount:t.value.queryCharacterRanking.entries[u].voteCount,firstVoteCount:t.value.queryCharacterRanking.entries[u].firstVoteCount,firstVotePercentage:y(t.value.queryCharacterRanking.entries[u].firstVotePercentage)})}_.value.push({name:"无主动率",active:y(t.value.queryCPSingle.noneActive),displayRank:"-",voteCount:"-",firstVoteCount:"-",firstVotePercentage:"-"})}}),I(d=>{alert(d.message),console.log(d.message)});const T=f(()=>[{name:"主动率",key:"active"},{name:"名次",key:"displayRank"},{name:"角色名",key:"name"},{name:"票数",key:"voteCount"},{name:"本命数",key:"firstVoteCount"},{name:"本命率",key:"firstVotePercentage"}]),A=[{name:"角色名",key:"name"}],B=f(()=>T.value.filter(d=>!A.find(v=>v.key===d.key))),_=l([]);return(d,v)=>{const u=W("router-link");return r(),o("div",G,[e("div",H,[e("div",J,[K,e("div",null,[X,e("span",Z,a(s(p)),1)])]),e("span",ee,a(s(p)),1),e("div",te,[e("div",null,[ne,e("div",null,a(s(q)),1)]),e("div",null,[ae,e("div",null,a(s(b)),1)]),e("div",null,[re,e("div",null,a(s(S)),1)]),e("div",null,[se,e("div",null,a(s(P)),1)]),e("div",null,[oe,e("div",null,a(s(w)),1)]),e("div",null,[ie,e("div",null,a(s(V)),1)])])]),le,e("div",ce,[ue,e("div",de,[e("div",ve,[(r(),o(g,null,m(A,n=>e("div",{key:n.key,class:z({"flex-grow":n.key==="name"})},[e("div",ye,[e("div",null,a(n.name),1)]),(r(!0),o(g,null,m(s(_),i=>(r(),o("div",{key:i.name},[n.key==="name"&&i[n.key]!="无主动率"?(r(),L(u,{key:0,class:"block p-1 truncate max-w-30 md:max-w-none",to:"/characterSingleDetail?rank="+i.rank},{default:M(()=>[C(a(i.name),1)]),_:2},1032,["to"])):(r(),o("div",ge,a(i[n.key]),1))]))),128))],2)),64))]),e("div",me,[(r(!0),o(g,null,m(s(B),n=>(r(),o("div",{key:n.key,class:"min-w-26"},[e("div",pe,[e("div",null,a(n.name),1)]),(r(!0),o(g,null,m(s(_),i=>(r(),o("div",{key:i.name},[e("div",_e,a(i[n.key]),1)]))),128))]))),128))])])]),e("div",ke,[he,(r(!0),o(g,null,m(s(R),n=>(r(),o("div",{key:n,class:"py-0.5 break-words"},a(n),1))),128))])])}}});typeof Y=="function"&&Y(fe);export{fe as default};
//# sourceMappingURL=CoupleReason-dabe5fa0.js.map
