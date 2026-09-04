import{_ as L}from"./Questionnaire.vue_vue_type_script_setup_true_lang-2fa7606f.js";import{g as F,a as N,s as M,d as W,G as H,_ as J}from"./Graph-41af3e26.js";import{d as K,a as o,m as P,u as X,g as Z,w as Y,t as k,s as ee,o as s,b as i,e,f as a,h as n,c as I,v as B,j as g,F as C,i as x,y as te,p as G,k as ne,r as ae,l as O}from"./index-6eea312f.js";import{t as y}from"./numberFormat-0203f5e2.js";import{g as b}from"./decodeAdditionalConstraint-5d07289b.js";import"./Questionnaire-55179045.js";import"./questionnaire-5ec436a8.js";import"./lz-string-0e91bc36.js";const re={class:"mx-1 my-3"},se={class:"mb-0 md:mx-5 p-3 space-y-3 bg-white bg-opacity-80 rounded-t md:bg-opacity-0 md:rounded md:flex md:flex-wrap md:justify-between md:items-center"},oe={class:"flex items-center"},ie=e("img",{src:"https://s3c.lilywhite.cc/thvote/imgs/nav/couple@100px.png",class:"w-10 h-10 col-span-1 row-span-2 rounded"},null,-1),le=e("h2",{class:"text-3xl font-light"},"CP信息",-1),ce={class:"text-xl hidden md:inline-block"},ue={class:"text-xl md:hidden"},de={class:"grid grid-cols-3 md:grid-cols-6 gap-1 text-sm md:text-base text-center"},ve=e("div",null,"票数",-1),ye=e("div",null,"本命票数",-1),ge=e("div",null,"本命率",-1),me=e("div",null,"票数全局占比",-1),pe=e("div",null,"本命全局占比",-1),_e=e("div",null,"投票理由",-1),he={key:1},fe=e("div",{class:"md:mx-5 p-3 py-1 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},[g(" * 本页面为单独CP的详细信息页面，下面每个栏目的内容分别有各自的说明"),e("br")],-1),ke={class:"md:mx-5 p-3"},Ce=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"角色与主动方倾向信息信息",-1),xe={class:"flex bg-white"},qe={class:"flex-grow flex"},Se={class:"p-1 whitespace-nowrap border-b border-accent-600"},Pe={key:1,class:"p-1 truncate max-w-30 md:max-w-none"},be={class:"flex flex-nowrap overflow-auto"},we={class:"p-1 whitespace-nowrap border-b border-accent-600"},Re={class:"p-1 truncate max-w-30 md:max-w-none"},Ve={class:"md:mx-5 p-3"},Ae=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"投票演进",-1),$e={class:"py-1 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},De=e("br",null,null,-1),Te=e("br",null,null,-1),Ee=K({__name:"CoupleSingleDetail",setup(Fe){const c=ne(),m=o(Number(c.query.rank?Array.isArray(c.query.rank)?c.query.rank[0]:c.query.rank:1)),p=P(()=>String(c.query.q?Array.isArray(c.query.q)?c.query.q[0]:c.query.q:"")),_=o("ID："+m.value),w=o(-1),R=o(-1),V=o(-1),A=o(-1),$=o(-1),h=o(-1),D=o([]),T=o("NONE"),{result:t,loading:U,onError:j}=X(Z`
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
  `,b(p.value)===""?{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,rank:m.value}:{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,rank:m.value,query:b(p.value)});Y(()=>{U.value?k.isStarted()||k.start():k.isStarted()&&k.done()}),Y(()=>{if(t.value&&(t.value.queryCPSingle&&(_.value=t.value.queryCPSingle.cp.a+" x "+t.value.queryCPSingle.cp.b+(t.value.queryCPSingle.cp.c?" x "+t.value.queryCPSingle.cp.c:""),ee(_.value+" - 第⑩回 中文东方人气投票"),T.value='cp=("'+t.value.queryCPSingle.cp.a+'","'+t.value.queryCPSingle.cp.b+(t.value.queryCPSingle.cp.c?'","'+t.value.queryCPSingle.cp.c:"")+'")',w.value=t.value.queryCPSingle.voteCount,R.value=t.value.queryCPSingle.firstVoteCount,V.value=y(t.value.queryCPSingle.firstVotePercentage),A.value=y(t.value.queryCPSingle.votePercentage),$.value=y(t.value.queryCPSingle.firstPercentage),h.value=t.value.queryCPSingle.numReasons,D.value.push(F("总票数",t.value.queryCPSingle.trend),N("新增票数",t.value.queryCPSingle.trend),F("总本命票数",t.value.queryCPSingle.trendFirst),N("新增本命票",t.value.queryCPSingle.trendFirst))),t.value.queryCharacterRanking.entries&&t.value.queryCPSingle)){const d=["a","b","c"];for(const v of d){const l=t.value.queryCharacterRanking.entries.findIndex(S=>{var r;return S.name===(((r=t.value)==null?void 0:r.queryCPSingle.cp[v])||"ERROR")});if(l===-1)continue;const q=v+"Active";f.value.push({rank:t.value.queryCharacterRanking.entries[l].rank,name:t.value.queryCPSingle.cp[v]||"ERROR",active:y(t.value.queryCPSingle[q]),displayRank:t.value.queryCharacterRanking.entries[l].displayRank,voteCount:t.value.queryCharacterRanking.entries[l].voteCount,firstVoteCount:t.value.queryCharacterRanking.entries[l].firstVoteCount,firstVotePercentage:y(t.value.queryCharacterRanking.entries[l].firstVotePercentage)})}f.value.push({name:"无主动率",active:y(t.value.queryCPSingle.noneActive),displayRank:"-",voteCount:"-",firstVoteCount:"-",firstVotePercentage:"-"})}}),j(d=>{alert(d.message),console.log(d.message)});const Q=P(()=>[{name:"主动率",key:"active"},{name:"名次",key:"displayRank"},{name:"角色名",key:"name"},{name:"票数",key:"voteCount"},{name:"本命数",key:"firstVoteCount"},{name:"本命率",key:"firstVotePercentage"}]),E=[{name:"角色名",key:"name"}],z=P(()=>Q.value.filter(d=>!E.find(v=>v.key===d.key))),f=o([]);return(d,v)=>{const l=ae("router-link"),q=J,S=L;return s(),i("div",re,[e("div",se,[e("div",oe,[ie,e("div",null,[le,e("span",ce,a(n(_)),1)])]),e("span",ue,a(n(_)),1),e("div",de,[e("div",null,[ve,e("div",null,a(n(w)),1)]),e("div",null,[ye,e("div",null,a(n(R)),1)]),e("div",null,[ge,e("div",null,a(n(V)),1)]),e("div",null,[me,e("div",null,a(n(A)),1)]),e("div",null,[pe,e("div",null,a(n($)),1)]),e("div",null,[_e,n(h)>0?(s(),I(l,{key:0,class:"underline",to:"/coupleReason?rank="+n(m)+(n(b)(n(p))===""?"":"&q="+n(p))},{default:B(()=>[g(a(n(h)+"(点此查看)"),1)]),_:1},8,["to"])):(s(),i("div",he,a(n(h)),1))])])]),fe,e("div",ke,[Ce,e("div",xe,[e("div",qe,[(s(),i(C,null,x(E,r=>e("div",{key:r.key,class:te({"flex-grow":r.key==="name"})},[e("div",Se,[e("div",null,a(r.name),1)]),(s(!0),i(C,null,x(n(f),u=>(s(),i("div",{key:u.name},[r.key==="name"&&u[r.key]!="无主动率"?(s(),I(l,{key:0,class:"block p-1 truncate max-w-30 md:max-w-none",to:"/characterSingleDetail?rank="+u.rank},{default:B(()=>[g(a(u.name),1)]),_:2},1032,["to"])):(s(),i("div",Pe,a(u[r.key]),1))]))),128))],2)),64))]),e("div",be,[(s(!0),i(C,null,x(n(z),r=>(s(),i("div",{key:r.key,class:"min-w-26"},[e("div",we,[e("div",null,a(r.name),1)]),(s(!0),i(C,null,x(n(f),u=>(s(),i("div",{key:u.name},[e("div",Re,a(u[r.key]),1)]))),128))]))),128))])])]),e("div",Ve,[Ae,e("div",$e,[g(" * 该图表表示该角色随着投票进程的票数变化情况。"),De,g(" * 投票日期："+a(n(M)+" ~ "+n(W))+"。",1),Te,g(" * 通过拖动底部和右侧的滑柄或在图表上缩放（鼠标或手指）可以筛选数据范围，也可以点击顶部的图例开关某个数据的显示。 ")]),G(q,{"x-axis":n(H),data:n(D),class:"max-w-4xl pt-3 mx-auto"},null,8,["x-axis","data"])]),G(S,{class:"md:mx-5",q:n(T)},null,8,["q"])])}}});typeof O=="function"&&O(Ee);export{Ee as default};
//# sourceMappingURL=CoupleSingleDetail-c53f60b2.js.map
