import{d as Q,e as _,f as a,g as $,h,w as x,i as l,s as k,o as v,a as q,b as e,t as i,u as r,j as b,F as w,k as A,l as S}from"./index-c1d6c5d6.js";import{f as F,q as T}from"./Questionnaire-c74696dd.js";import"./questionnaire-b69f5aad.js";const O={class:"mx-1 my-3"},Y={class:"mb-0 md:mx-5 p-3 space-y-3 bg-white bg-opacity-80 rounded-t md:bg-opacity-0 md:rounded md:flex md:flex-wrap md:justify-between md:items-center"},C={class:"flex items-center"},B={class:"text-xl hidden md:inline-block"},E={class:"text-xl md:hidden"},M={class:"grid grid-cols-3 gap-1 text-sm md:text-base text-center"},N={class:"md:mx-5 p-3 divide-y-1 divide-accent-300"},U=Q({__name:"QuestionnaireInputDetail",setup(j){const s=_(),u=a(String(s.query.qid?Array.isArray(s.query.qid)?s.query.qid[0]:s.query.qid:"q11011")),m=a(String(s.query.q?Array.isArray(s.query.q)?s.query.q[0]:s.query.q:"")),o=a("qid: "+u.value),y=a(-1),c=a(-1),p=a(-1),f=a([]),{result:n,loading:I,onError:D}=$(h`
    query ($voteStart: DateTimeUtc!, $voteYear: Int!, $query: String, $questionsOfInterest: [String!]!) {
      queryQuestionnaire(
        voteStart: $voteStart
        voteYear: $voteYear
        query: $query
        questionsOfInterest: $questionsOfInterest
      ) {
        entries {
          questionId
          answersStr
          totalAnswers
          totalMale
          totalFemale
        }
      }
    }
  `,m.value===""?{voteStart:new Date(Date.UTC(2023,11,29,10)),voteYear:11,questionsOfInterest:[u.value]}:{voteStart:new Date(Date.UTC(2023,11,29,10)),voteYear:11,query:m.value,questionsOfInterest:[u.value]});return x(()=>{I.value?l.isStarted()||l.start():l.isStarted()&&l.done()}),x(()=>{n.value&&n.value.queryQuestionnaire&&(o.value=F(T(n.value.queryQuestionnaire.entries[0].questionId)).question,k(o.value),y.value=n.value.queryQuestionnaire.entries[0].totalAnswers,c.value=n.value.queryQuestionnaire.entries[0].totalMale,p.value=n.value.queryQuestionnaire.entries[0].totalFemale,f.value=n.value.queryQuestionnaire.entries[0].answersStr)}),D(d=>{alert(d.message),console.log(d.message)}),(d,t)=>(v(),q(w,null,[e("div",O,[e("div",Y,[e("div",C,[t[1]||(t[1]=e("img",{src:"https://asset.lilywhite.cc/thvote/imgs/nav/questionnaireDetail@100px.png",class:"w-10 h-10 col-span-1 row-span-2 rounded"},null,-1)),e("div",null,[t[0]||(t[0]=e("h2",{class:"text-3xl font-light"},"问卷回答",-1)),e("span",B,i(r(o)),1)])]),e("span",E,i(r(o)),1),e("div",M,[e("div",null,[t[2]||(t[2]=e("div",null,"回答数",-1)),e("div",null,i(r(y)),1)]),e("div",null,[t[3]||(t[3]=e("div",null,"男性回答数",-1)),e("div",null,i(r(c)),1)]),e("div",null,[t[4]||(t[4]=e("div",null,"女性回答数",-1)),e("div",null,i(r(p)),1)])])])]),t[6]||(t[6]=e("div",{class:"md:mx-5 p-3 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},[b(" * 本页面列出所有投票的时候用户填写的问题内容"),e("br"),b(" * 可使用 Ctrl + F 或 ⌘ + F 调出浏览器自带的搜索功能进行搜索 ")],-1)),e("div",N,[t[5]||(t[5]=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"回答列表",-1)),(v(!0),q(w,null,A(r(f),g=>(v(),q("div",{key:g,class:"py-0.5 break-words"},i(g),1))),128))])],64))}});typeof S=="function"&&S(U);export{U as default};
//# sourceMappingURL=QuestionnaireInputDetail-3f819ef5.js.map
