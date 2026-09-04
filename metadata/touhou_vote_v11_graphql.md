# 中国第 11 回官方站 GraphQL 接口核对

核对日期：2026-08-15。仅使用公开静态资源、source map、GraphQL introspection 与只读 query。

## 固定入口与基础变量

- 结果站：`https://touhou.vote/v11/`
- GraphQL：`https://touhou.vote/res-be/graphql`
- `voteStart`: `2023-12-29T10:00:00.000Z`
- `voteYear`: `11`
- `query`: 可选的条件表达式；无筛选时官方前端直接省略该变量。

可直接导入的完整 query 常量、变量 helper 和标准库 HTTP 客户端见
`scripts_pipeline/touhou_vote_v11_graphql.py`。

## 音乐

官方页面实际调用：

- `queryMusicRanking(query, voteStart, voteYear)`：`global` 与完整 `entries` 排名。
- `queryMusicSingle(query, voteStart, voteYear, rank)`：单曲详情、理由、小时趋势。
- `queryMusicTrend(voteStart, voteYear, names)`：多首曲目的 `trend` / `trendFirst`。

关键结果字段：

`rank`, `displayRank`, `name`, `voteCount`, `firstVoteCount`,
`firstVotePercentage`, `firstVoteCountWeighted`, `votePercentage`,
`firstPercentage`, `maleVoteCount`, `malePercentagePerChar`,
`malePercentagePerTotal`, `femaleVoteCount`, `femalePercentagePerChar`,
`femalePercentagePerTotal`, `album`, `nameJpn`, `firstAppearance`。

趋势变量示例：

```json
{
  "voteStart": "2023-12-29T10:00:00.000Z",
  "voteYear": 11,
  "names": ["哈德曼的妖怪少女"]
}
```

实测该曲返回 1 个 `Trends`，其中 `trend` 258 点、`trendFirst` 132 点。
返回数组按传入 `names` 顺序对应。

## CP

官方页面实际调用：

- `queryCPRanking(query, voteStart, voteYear)`：完整 CP 排名。
- `queryCPSingle(query, voteStart, voteYear, rank)`：单条 CP 的理由与趋势。
- schema 另有 `queryCPTrend(voteStart, voteYear, ranks)`，返回 `[Trends!]!`。

关键结果字段：

`rank`, `displayRank`, `cp { a b c }`, `aActive`, `bActive`,
`cActive`, `noneActive`, `voteCount`, `firstVoteCount`,
`firstVotePercentage`, `firstVoteCountWeighted`, `votePercentage`,
`firstPercentage` 以及男女票数/比例字段。

单项变量中的 `rank` 是接口原始 `rank: Int!`；不是角色名组合。`cp.c` 可为
`null`。

## 问卷分布、趋势与条件排名

分类问卷的实际 query 同时请求：

- `queryQuestionnaire(query, voteStart, voteYear, questionsOfInterest)`
- `queryCompletionRates(query, voteStart, voteYear)`

其中 `questionsOfInterest` 为 `q` 前缀字符串，例如 `["q11011"]`。分类结果：

```graphql
entries {
  questionId
  answersCat { aid totalVotes maleVotes femaleVotes }
  totalAnswers
  totalMale
  totalFemale
}
```

开放题页面用同一字段，改取 `answersStr`。

问卷趋势页的实际 query 同时请求：

- `queryGlobalStats(query, voteStart, voteYear)`
- `queryQuestionnaireTrend(query, voteStart, voteYear, questionIds)`

`questionIds` 同样是 `["q11011"]` 形式；返回 `[Trends!]!`，每项含
`trend { hrs cnt }` 和 `trendFirst { hrs cnt }`。无筛选实测 `q11011` 返回
361 个小时点，`trendFirst` 为空数组。

“条件排名”不是单独 endpoint：把同一个 `query` 字符串传给
`queryMusicRanking`、`queryCPRanking`、`queryCharacterRanking` 即可。

### 条件 DSL

官方高级搜索组件公开的语法：

```text
q11011=1101101
chars:["东风谷早苗", "博丽灵梦"]
chars_first="东风谷早苗"
musics:["信仰是为了虚幻之人", "Native Faith"]
musics_first="信仰是为了虚幻之人"
```

- 一个数组内是 OR。
- 重复规则可用 `AND` 表示同时满足。
- 不同规则支持 `AND`、`OR` 与圆括号。
- 例：`q11011=1101102 AND chars:["博丽灵梦"]`。
- 问题 ID 带 `q`，答案 ID 不带 `q`。第 11 回性别题为 `q11011`：
  `1101101=男`、`1101102=女`。

前端 GUI URL 参数 `a` 只是 LZ-string 压缩后的筛选对象；主爬虫可以跳过
这一层，直接把解码后的 DSL 放进 GraphQL `variables.query`。

实测 `query: "q11011=1101102"` 成功返回女性子样本：

- `queryGlobalStats.numVote = 2240`
- 音乐排名 506 条，`global.totalVotes = 1552`
- CP 排名 230 条，`global.totalVotes = 1603`
- 无 GraphQL error

## 同人作品提名（Doujin/Dojin）

这一页没有公开结果 GraphQL query。`Doujin-f64f63b8.js` / source map 将前十
作品与甄选评论直接硬编码在前端，页面显示“总票数：1272”。GraphQL Query
introspection 中没有 `queryDojinRanking` 或同类字段。

可公开查询的只有 `queryGlobalStats.numDoujin` 聚合量；无筛选实测为 1237，
与静态页 1272 不同，因此两者不可互换。schema 中的
`getSubmitDojinVote(voteToken: String!)` 是凭投票 token 读取单份提交，不是公开
结果列表，也不应作为结果爬取入口。

同人结果应只读抓取：

- `https://touhou.vote/v11/assets/Doujin-f64f63b8.js`
- `https://touhou.vote/v11/assets/Doujin-f64f63b8.js.map`

注意页面文件拼作 `Doujin`，GraphQL schema 拼作 `Dojin`。

## 证据静态资源

- 路由入口：`/v11/assets/index-c1d6c5d6.js`
- 音乐排名：`MusicDetail-50ca87bf.js`
- 音乐演进：`MusicEvolution-5ca45e38.js`
- CP 排名：`CoupleDetail-fbcdfb55.js`
- CP 单项：`CoupleSingleDetail-23e5fe25.js`
- 问卷分布组件：`Questionnaire.vue_vue_type_script_setup_true_lang-49f6f247.js`
- 问卷趋势：`QuestionnaireDetail-3e0c9466.js`
- 高级搜索：`AdvancedSearch.vue_vue_type_script_setup_true_lang-5a7fd4f0.js`
- 条件解码：`decodeAdditionalConstraint-7c1b9997.js`
- 问卷定义：`questionnaire-b69f5aad.js`
- 同人静态页：`Doujin-f64f63b8.js`

上述 `.js` 均有同名 `.js.map`，source map 内含原始 Vue/TypeScript 源码。
