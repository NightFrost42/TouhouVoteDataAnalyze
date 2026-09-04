import{d as N,e as U,f as u,g as j,h as O,w as D,i as f,s as z,r as L,o as s,a as l,b as e,t as r,u as o,j as x,F as g,k as m,y as M,c as Q,v as W,q,l as Y}from"./index-c1d6c5d6.js";import{t as y}from"./numberFormat-0203f5e2.js";import{g as F}from"./decodeAdditionalConstraint-7c1b9997.js";import"./lz-string-35001fa0.js";const G={class:"mx-1 my-3"},H={class:"mb-0 md:mx-5 p-3 space-y-3 bg-white bg-opacity-80 rounded-t md:bg-opacity-0 md:rounded md:flex md:flex-wrap md:justify-between md:items-center"},J={class:"flex items-center"},K={class:"text-xl hidden md:inline-block"},X={class:"text-xl md:hidden"},Z={class:"grid grid-cols-3 md:grid-cols-6 gap-1 text-sm md:text-base text-center"},ee={class:"md:mx-5 p-3"},te={class:"flex bg-white"},ne={class:"flex-grow flex"},ae={class:"p-1 whitespace-nowrap border-b border-accent-600"},re={key:1,class:"p-1 truncate max-w-30 md:max-w-none"},se={class:"flex flex-nowrap overflow-auto"},oe={class:"p-1 whitespace-nowrap border-b border-accent-600"},le={class:"p-1 truncate max-w-30 md:max-w-none"},ie={class:"md:mx-5 p-3 divide-y-1 divide-accent-300"},ue=N({__name:"CoupleReason",setup(de){const d=U(),C=u(Number(d.query.rank?Array.isArray(d.query.rank)?d.query.rank[0]:d.query.rank:1)),b=q(()=>String(d.query.q?Array.isArray(d.query.q)?d.query.q[0]:d.query.q:"")),p=u("ID："+C.value),S=u(-1),P=u(-1),w=u(-1),h=u(-1),R=u(-1),_=u([]),V=u(-1),{result:n,loading:E,onError:I}=j(O`
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
  `,F(b.value)===""?{voteStart:new Date(Date.UTC(2023,11,29,10)),voteYear:11,rank:C.value}:{voteStart:new Date(Date.UTC(2023,11,29,10)),voteYear:11,rank:C.value,query:F(b.value)});D(()=>{E.value?f.isStarted()||f.start():f.isStarted()&&f.done()}),D(()=>{if(n.value&&(n.value.queryCPSingle&&(p.value=n.value.queryCPSingle.cp.a+" x "+n.value.queryCPSingle.cp.b+(n.value.queryCPSingle.cp.c?" x "+n.value.queryCPSingle.cp.c:""),z(p.value),S.value=n.value.queryCPSingle.voteCount,P.value=n.value.queryCPSingle.firstVoteCount,w.value=y(n.value.queryCPSingle.firstVotePercentage),h.value=y(n.value.queryCPSingle.votePercentage),R.value=y(n.value.queryCPSingle.firstPercentage),_.value=n.value.queryCPSingle.reasons,V.value=n.value.queryCPSingle.numReasons),n.value.queryCharacterRanking.entries&&n.value.queryCPSingle)){const c=["a","b","c"];for(const t of c){const v=n.value.queryCharacterRanking.entries.findIndex(i=>{var $;return i.name===((($=n.value)==null?void 0:$.queryCPSingle.cp[t])||"ERROR")});if(v===-1)continue;const a=t+"Active";k.value.push({rank:n.value.queryCharacterRanking.entries[v].rank,name:n.value.queryCPSingle.cp[t]||"ERROR",active:y(n.value.queryCPSingle[a]),displayRank:n.value.queryCharacterRanking.entries[v].displayRank,voteCount:n.value.queryCharacterRanking.entries[v].voteCount,firstVoteCount:n.value.queryCharacterRanking.entries[v].firstVoteCount,firstVotePercentage:y(n.value.queryCharacterRanking.entries[v].firstVotePercentage)})}k.value.push({name:"无主动率",active:y(n.value.queryCPSingle.noneActive),displayRank:"-",voteCount:"-",firstVoteCount:"-",firstVotePercentage:"-"})}}),I(c=>{alert(c.message),console.log(c.message)});const T=q(()=>[{name:"主动率",key:"active"},{name:"名次",key:"displayRank"},{name:"角色名",key:"name"},{name:"票数",key:"voteCount"},{name:"本命数",key:"firstVoteCount"},{name:"本命率",key:"firstVotePercentage"}]),A=[{name:"角色名",key:"name"}],B=q(()=>T.value.filter(c=>!A.find(t=>t.key===c.key))),k=u([]);return(c,t)=>{const v=L("router-link");return s(),l("div",G,[e("div",H,[e("div",J,[t[1]||(t[1]=e("img",{src:"https://asset.lilywhite.cc/thvote/imgs/nav/couple@100px.png",class:"w-10 h-10 col-span-1 row-span-2 rounded"},null,-1)),e("div",null,[t[0]||(t[0]=e("h2",{class:"text-3xl font-light"},"投票理由",-1)),e("span",K,r(o(p)),1)])]),e("span",X,r(o(p)),1),e("div",Z,[e("div",null,[t[2]||(t[2]=e("div",null,"票数",-1)),e("div",null,r(o(S)),1)]),e("div",null,[t[3]||(t[3]=e("div",null,"本命票数",-1)),e("div",null,r(o(P)),1)]),e("div",null,[t[4]||(t[4]=e("div",null,"本命率",-1)),e("div",null,r(o(w)),1)]),e("div",null,[t[5]||(t[5]=e("div",null,"票数全局占比",-1)),e("div",null,r(o(h)),1)]),e("div",null,[t[6]||(t[6]=e("div",null,"本命全局占比",-1)),e("div",null,r(o(R)),1)]),e("div",null,[t[7]||(t[7]=e("div",null,"理由数量",-1)),e("div",null,r(o(V)),1)])])]),t[10]||(t[10]=e("div",{class:"md:mx-5 p-3 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},[x(" * 本页面列出所有投票的时候用户提交的投票理由"),e("br"),x(" * 可使用 Ctrl + F 或 ⌘ + F 调出浏览器自带的搜索功能进行搜索 ")],-1)),e("div",ee,[t[8]||(t[8]=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"角色与主动方倾向信息信息",-1)),e("div",te,[e("div",ne,[(s(),l(g,null,m(A,a=>e("div",{key:a.key,class:M({"flex-grow":a.key==="name"})},[e("div",ae,[e("div",null,r(a.name),1)]),(s(!0),l(g,null,m(o(k),i=>(s(),l("div",{key:i.name},[a.key==="name"&&i[a.key]!="无主动率"?(s(),Q(v,{key:0,class:"block p-1 truncate max-w-30 md:max-w-none",to:"/characterSingleDetail?rank="+i.rank},{default:W(()=>[x(r(i.name),1)]),_:2},1032,["to"])):(s(),l("div",re,r(i[a.key]),1))]))),128))],2)),64))]),e("div",se,[(s(!0),l(g,null,m(o(B),a=>(s(),l("div",{key:a.key,class:"min-w-26"},[e("div",oe,[e("div",null,r(a.name),1)]),(s(!0),l(g,null,m(o(k),i=>(s(),l("div",{key:i.name},[e("div",le,r(i[a.key]),1)]))),128))]))),128))])])]),e("div",ie,[t[9]||(t[9]=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"理由列表",-1)),(s(!0),l(g,null,m(o(_),a=>(s(),l("div",{key:a,class:"py-0.5 break-words"},r(a),1))),128))])])}}});typeof Y=="function"&&Y(ue);export{ue as default};
//# sourceMappingURL=CoupleReason-59592b6a.js.map
