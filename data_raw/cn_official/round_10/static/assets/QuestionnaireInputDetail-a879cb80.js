import{d as S,a,u as I,g as D,w as f,t as r,s as Q,o as d,b as c,e,f as n,h as i,F as h,i as $,j as g,k,l as x}from"./index-6eea312f.js";import{f as A,q as F}from"./Questionnaire-55179045.js";import"./questionnaire-5ec436a8.js";const T={class:"mx-1 my-3"},O={class:"mb-0 md:mx-5 p-3 space-y-3 bg-white bg-opacity-80 rounded-t md:bg-opacity-0 md:rounded md:flex md:flex-wrap md:justify-between md:items-center"},Y={class:"flex items-center"},C=e("img",{src:"https://s3c.lilywhite.cc/thvote/imgs/nav/questionnaireDetail@100px.png",class:"w-10 h-10 col-span-1 row-span-2 rounded"},null,-1),B=e("h2",{class:"text-3xl font-light"},"问卷回答",-1),E={class:"text-xl hidden md:inline-block"},M={class:"text-xl md:hidden"},N={class:"grid grid-cols-3 gap-1 text-sm md:text-base text-center"},U=e("div",null,"回答数",-1),j=e("div",null,"男性回答数",-1),V=e("div",null,"女性回答数",-1),L=e("div",{class:"md:mx-5 p-3 bg-white bg-opacity-80 rounded-b md:bg-opacity-0 text-sm italic text-gray-700"},[g(" * 本页面列出所有投票的时候用户填写的问题内容"),e("br"),g(" * 可使用 Ctrl + F 或 ⌘ + F 调出浏览器自带的搜索功能进行搜索 ")],-1),R={class:"md:mx-5 p-3 divide-y-1 divide-accent-300"},W=e("div",{class:"text-2xl py-0.5 border-b border-accent-600"},"回答列表",-1),z=S({__name:"QuestionnaireInputDetail",setup(G){const t=k(),l=a(String(t.query.qid?Array.isArray(t.query.qid)?t.query.qid[0]:t.query.qid:"q11011")),v=a(String(t.query.q?Array.isArray(t.query.q)?t.query.q[0]:t.query.q:"")),o=a("qid: "+l.value),q=a(-1),m=a(-1),y=a(-1),_=a([]),{result:s,loading:b,onError:w}=I(D`
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
  `,v.value===""?{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,questionsOfInterest:[l.value]}:{voteStart:new Date(Date.UTC(2022,5,17,10)),voteYear:10,query:v.value,questionsOfInterest:[l.value]});return f(()=>{b.value?r.isStarted()||r.start():r.isStarted()&&r.done()}),f(()=>{s.value&&s.value.queryQuestionnaire&&(o.value=A(F(s.value.queryQuestionnaire.entries[0].questionId)).question,Q(o.value+" - 第⑩回 中文东方人气投票"),q.value=s.value.queryQuestionnaire.entries[0].totalAnswers,m.value=s.value.queryQuestionnaire.entries[0].totalMale,y.value=s.value.queryQuestionnaire.entries[0].totalFemale,_.value=s.value.queryQuestionnaire.entries[0].answersStr)}),w(u=>{alert(u.message),console.log(u.message)}),(u,H)=>(d(),c(h,null,[e("div",T,[e("div",O,[e("div",Y,[C,e("div",null,[B,e("span",E,n(i(o)),1)])]),e("span",M,n(i(o)),1),e("div",N,[e("div",null,[U,e("div",null,n(i(q)),1)]),e("div",null,[j,e("div",null,n(i(m)),1)]),e("div",null,[V,e("div",null,n(i(y)),1)])])])]),L,e("div",R,[W,(d(!0),c(h,null,$(i(_),p=>(d(),c("div",{key:p,class:"py-0.5 break-words"},n(p),1))),128))])],64))}});typeof x=="function"&&x(z);export{z as default};
//# sourceMappingURL=QuestionnaireInputDetail-a879cb80.js.map
