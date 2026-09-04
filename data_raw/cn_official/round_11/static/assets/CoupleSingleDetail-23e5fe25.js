import{_ as L}from"./Questionnaire.vue_vue_type_script_setup_true_lang-49f6f247.js";import{g as F,a as N,s as M,d as W,G as H,_ as J}from"./Graph-4e483fd9.js";import{d as K,e as X,f as o,g as Z,h as ee,w as Y,i as x,s as te,r as ne,o as l,a as i,b as e,t as r,u as a,c as I,v as B,j as y,F as q,k as S,y as ae,n as G,q as w,l as O}from"./index-c1d6c5d6.js";import{t as g}from"./numberFormat-0203f5e2.js";import{g as _}from"./decodeAdditionalConstraint-7c1b9997.js";import"./Questionnaire-c74696dd.js";import"./questionnaire-b69f5aad.js";import"./lz-string-35001fa0.js";const re={class:"mx-1 my-3"},se={class:"mb-0 md:mx-5 p-3 space-y-3 bg-white bg-opacity-80 rounded-t md:bg-opacity-0 md:rounded md:flex md:flex-wrap md:justify-between md:items-center"},le={class:"flex items-center"},oe={class:"text-xl hidden md:inline-block"},ie={class:"text-xl md:hidden"},ue={class:"grid grid-cols-3 md:grid-cols-6 gap-1 text-sm md:text-base text-center"},de={key:1},ve={class:"md:mx-5 p-3"},ce={class:"flex bg-white"},ye={class:"flex-grow flex"},ge={class:"p-1 whitespace-nowrap border-b border-accent-600"},me={key:1,class:"p-1 truncate max-w-30 md:max-w-none"},pe={class:"flex flex-nowrap overflow-auto"},fe={class:"p-1 whitespace-nowrap border-b border-accent-600"},ke={class:"p-1 truncate max-w-30 md:max-w-none"},Ce={class:"md:mx-5 p-3"},xe={class:"py-1 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},qe=K({__name:"CoupleSingleDetail",setup(Se){const d=X(),m=o(Number(d.query.rank?Array.isArray(d.query.rank)?d.query.rank[0]:d.query.rank:1)),p=w(()=>String(d.query.q?Array.isArray(d.query.q)?d.query.q[0]:d.query.q:"")),f=o("ID："+m.value),h=o(-1),R=o(-1),V=o(-1),A=o(-1),$=o(-1),k=o(-1),D=o([]),T=o("NONE"),{result:n,loading:U,onError:j}=Z(ee`
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
        trend {
          hrs
          cnt
        }
        trendFirst {
          hrs
          cnt
        }
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
  `,_(p.value)===""?{voteStart:new Date(Date.UTC(2023,11,29,10)),voteYear:11,rank:m.value}:{voteStart:new Date(Date.UTC(2023,11,29,10)),voteYear:11,rank:m.value,query:_(p.value)});Y(()=>{U.value?x.isStarted()||x.start():x.isStarted()&&x.done()}),Y(()=>{if(n.value&&(n.value.queryCPSingle&&(f.value=n.value.queryCPSingle.cp.a+" x "+n.value.queryCPSingle.cp.b+(n.value.queryCPSingle.cp.c?" x "+n.value.queryCPSingle.cp.c:""),te(f.value),T.value='cp=("'+n.value.queryCPSingle.cp.a+'","'+n.value.queryCPSingle.cp.b+(n.value.queryCPSingle.cp.c?'","'+n.value.queryCPSingle.cp.c:"")+'")',h.value=n.value.queryCPSingle.voteCount,R.value=n.value.queryCPSingle.firstVoteCount,V.value=g(n.value.queryCPSingle.firstVotePercentage),A.value=g(n.value.queryCPSingle.votePercentage),$.value=g(n.value.queryCPSingle.firstPercentage),k.value=n.value.queryCPSingle.numReasons,D.value.push(F("总票数",n.value.queryCPSingle.trend),N("新增票数",n.value.queryCPSingle.trend),F("总本命票数",n.value.queryCPSingle.trendFirst),N("新增本命票",n.value.queryCPSingle.trendFirst))),n.value.queryCharacterRanking.entries&&n.value.queryCPSingle)){const c=["a","b","c"];for(const t of c){const u=n.value.queryCharacterRanking.entries.findIndex(b=>{var s;return b.name===(((s=n.value)==null?void 0:s.queryCPSingle.cp[t])||"ERROR")});if(u===-1)continue;const P=t+"Active";C.value.push({rank:n.value.queryCharacterRanking.entries[u].rank,name:n.value.queryCPSingle.cp[t]||"ERROR",active:g(n.value.queryCPSingle[P]),displayRank:n.value.queryCharacterRanking.entries[u].displayRank,voteCount:n.value.queryCharacterRanking.entries[u].voteCount,firstVoteCount:n.value.queryCharacterRanking.entries[u].firstVoteCount,firstVotePercentage:g(n.value.queryCharacterRanking.entries[u].firstVotePercentage)})}C.value.push({name:"无主动率",active:g(n.value.queryCPSingle.noneActive),displayRank:"-",voteCount:"-",firstVoteCount:"-",firstVotePercentage:"-"})}}),j(c=>{alert(c.message),console.log(c.message)});const Q=w(()=>[{name:"主动率",key:"active"},{name:"名次",key:"displayRank"},{name:"角色名",key:"name"},{name:"票数",key:"voteCount"},{name:"本命数",key:"firstVoteCount"},{name:"本命率",key:"firstVotePercentage"}]),E=[{name:"角色名",key:"name"}],z=w(()=>Q.value.filter(c=>!E.find(t=>t.key===c.key))),C=o([]);return(c,t)=>{const u=ne("router-link"),P=J,b=L;return l(),i("div",re,[e("div",se,[e("div",le,[t[1]||(t[1]=e("img",{src:"https://asset.lilywhite.cc/thvote/imgs/nav/couple@100px.png",class:"w-10 h-10 col-span-1 row-span-2 rounded"},null,-1)),e("div",null,[t[0]||(t[0]=e("h2",{class:"text-3xl font-light"},"CP信息",-1)),e("span",oe,r(a(f)),1)])]),e("span",ie,r(a(f)),1),e("div",ue,[e("div",null,[t[2]||(t[2]=e("div",null,"票数",-1)),e("div",null,r(a(h)),1)]),e("div",null,[t[3]||(t[3]=e("div",null,"本命票数",-1)),e("div",null,r(a(R)),1)]),e("div",null,[t[4]||(t[4]=e("div",null,"本命率",-1)),e("div",null,r(a(V)),1)]),e("div",null,[t[5]||(t[5]=e("div",null,"票数全局占比",-1)),e("div",null,r(a(A)),1)]),e("div",null,[t[6]||(t[6]=e("div",null,"本命全局占比",-1)),e("div",null,r(a($)),1)]),e("div",null,[t[7]||(t[7]=e("div",null,"投票理由",-1)),a(k)>0?(l(),I(u,{key:0,class:"underline",to:"/coupleReason?rank="+a(m)+(a(_)(a(p))===""?"":"&q="+a(p))},{default:B(()=>[y(r(a(k)+"(点此查看)"),1)]),_:1},8,["to"])):(l(),i("div",de,r(a(k)),1))])])]),t[14]||(t[14]=e("div",{class:"md:mx-5 p-3 py-1 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},[y(" * 本页面为单独CP的详细信息页面，下面每个栏目的内容分别有各自的说明"),e("br")],-1)),e("div",ve,[t[8]||(t[8]=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"角色与主动方倾向信息信息",-1)),e("div",ce,[e("div",ye,[(l(),i(q,null,S(E,s=>e("div",{key:s.key,class:ae({"flex-grow":s.key==="name"})},[e("div",ge,[e("div",null,r(s.name),1)]),(l(!0),i(q,null,S(a(C),v=>(l(),i("div",{key:v.name},[s.key==="name"&&v[s.key]!="无主动率"?(l(),I(u,{key:0,class:"block p-1 truncate max-w-30 md:max-w-none",to:"/characterSingleDetail?rank="+v.rank},{default:B(()=>[y(r(v.name),1)]),_:2},1032,["to"])):(l(),i("div",me,r(v[s.key]),1))]))),128))],2)),64))]),e("div",pe,[(l(!0),i(q,null,S(a(z),s=>(l(),i("div",{key:s.key,class:"min-w-26"},[e("div",fe,[e("div",null,r(s.name),1)]),(l(!0),i(q,null,S(a(C),v=>(l(),i("div",{key:v.name},[e("div",ke,r(v[s.key]),1)]))),128))]))),128))])])]),e("div",Ce,[t[13]||(t[13]=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"投票演进",-1)),e("div",xe,[t[9]||(t[9]=y(" * 该图表表示该角色随着投票进程的票数变化情况。",-1)),t[10]||(t[10]=e("br",null,null,-1)),y(" * 投票日期："+r(a(M)+" ~ "+a(W))+"。",1),t[11]||(t[11]=e("br",null,null,-1)),t[12]||(t[12]=y(" * 通过拖动底部和右侧的滑柄或在图表上缩放（鼠标或手指）可以筛选数据范围，也可以点击顶部的图例开关某个数据的显示。 ",-1))]),G(P,{"x-axis":a(H),data:a(D),class:"max-w-4xl pt-3 mx-auto"},null,8,["x-axis","data"])]),G(b,{class:"md:mx-5",q:a(T)},null,8,["q"])])}}});typeof O=="function"&&O(qe);export{qe as default};
//# sourceMappingURL=CoupleSingleDetail-23e5fe25.js.map
