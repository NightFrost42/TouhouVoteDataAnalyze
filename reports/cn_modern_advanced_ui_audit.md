# CN10 / CN11 现代站高级搜索只读审计

审计日期：2026-08-17  
范围：中国东方人气投票第 10、11 届结果站的角色、音乐、CP 结果页及共用 `AdvancedSearch` 组件。  
方法：仅检查已经缓存的官网 HTML、JavaScript、source map、GraphQL 原始响应及本地清单；本次没有发起网络请求，也没有抓取评论、理由、图片、字体或个人投票记录。

## 结论

1. CN10 与 CN11 的高级搜索能力在语义上相同，区别只有届次参数、投票起始时间和当届的角色/音乐/问卷定义。
2. 页面所谓“高级搜索”实际包含两层完全不同的筛选：
   - `keyword`、`searchRange`、`minCount`、`maxCount` 只在浏览器中筛选已经返回的排名，不进入 GraphQL。为它们重复抓取会制造纯重复数据。
   - 角色、音乐、本命和问卷答案条件会编译为 `query: String`，由 GraphQL 后端重新计算条件样本的排名。这一层才是需要归档的数值数据。
3. 服务器条件语言支持任意 `AND`、`OR` 和括号组合，因此“爬完所有高级搜索组合”没有有限上界。完整覆盖应定义为“完整保存接口契约和所有分析原子条件”，而不是枚举所有布尔表达式。
4. 问卷单选/多选答案的一阶条件排名已经抓全：CN10 为 387 个实际可见选项，CN11 为 403 个实际可见选项。目录里另各有 3 个来自开放题定义的空白占位选项；它们都返回零票，不属于 GUI 可选条件，应保留原始证据但从分析层排除。
5. 为控制体量，条件响应保留样本总体、各部门全局量、条目标识、`voteCount` 和 `firstVoteCount` 已足够计算条件率、差值、lift 和大部分列联表。页面上的重复百分比、显示格式、图片和理由不需要随每个条件重复抓取。

## 两层筛选的边界

| 层级 | URL / 组件字段 | 作用 | 是否请求后端 | 抓取建议 |
|---|---|---|---|---|
| 结果内筛选 | `keyword` | 以大小写不敏感的 JavaScript 正则匹配条目元数据 | 否 | 不抓；基于本地主榜复现 |
| 结果内筛选 | `searchRange` | 位掩码，选择关键词匹配字段 | 否 | 不抓；保存映射即可 |
| 结果内筛选 | `minCount` / `maxCount` | 仅按 `voteCount` 截取返回行 | 否 | 不抓；本地计算 |
| 投票样本筛选 | URL `a` | LZ-string 压缩的 GUI 条件对象 | 是，先解码成 DSL | 不把压缩 URL 当数据；归档解码后的 DSL |
| 投票样本筛选 | URL `q` | 指令模式下的原始 DSL | 是 | 保存规范化 DSL 与 GraphQL variables |
| 模式选择 | `gui=1/0` | 选择使用 `a` 解码结果还是 `q` | 间接 | 只需在来源元数据中说明 |

三个页面的本地关键词字段如下：

| 页面 | `searchRange` 对应字段 |
|---|---|
| 角色 | 所属作品 `characterOrigin`、角色名 `name`、日文名 `nameJpn` |
| 音乐 | 所属专辑 `album`、曲目名 `name`、日文名 `nameJpn` |
| CP | 角色 1/2/3，结果对象内部为 `aName` / `bName` / `cName` |

位掩码通用约定为：`1`、`2`、`4` 分别代表三个字段，组合值为 `3`、`5`、`6`、`7`。但 CP 页存在一个仅影响前端关键词筛选的映射错误：高级搜索组件把“角色1/2/3”编码为 bit `4/2/1`，CP 页却把 bit `1/2/4` 解码为 `aName/bName/cName`。因此只选“角色1”实际匹配 `cName`，只选“角色3”实际匹配 `aName`；两届源码都有这一问题。它不会改变 GraphQL 条件数据，抓取程序也不应依赖这个前端筛选。

## 服务器端条件维度与组合规则

高级搜索 GUI 暴露的样本条件是：

| 条件 | DSL | GUI 数量/语义 |
|---|---|---|
| 投过角色 | `chars:["角色名"]` | 可添加多个；GUI 实际生成多个单元素条件并用 `AND` 连接 |
| 角色本命 | `chars_first="角色名"` | 最多一个 |
| 投过音乐 | `musics:["曲名"]` | 可添加多个；GUI 实际生成多个单元素条件并用 `AND` 连接 |
| 音乐本命 | `musics_first="曲名"` | 最多一个 |
| 问卷答案 | `q问题ID=答案ID` | GUI 只列 `Single` 与 `Multiple`，不列 `Input` 开放题 |

指令模式另外明确支持：

- 单个数组内为 OR，例如 `chars:["博丽灵梦","雾雨魔理沙"]`；
- 重复规则或不同规则可用 `AND`，例如 `chars:["博丽灵梦"] AND musics:["恋色Master spark"]`；
- 规则可用 `OR` 并列；
- 圆括号可调整优先级，例如 `(q11011=1101101 AND chars:["博丽灵梦"]) OR musics_first="恋色Master spark"`。

没有在页面契约中发现 CP 选择条件、否定条件、数值比较条件或对开放题文本的服务器端筛选。人口属性并不是独立关键字，而是相应问卷答案的 `q...=...` 条件。

GUI 对问卷类型的实际覆盖为：

| 届次 | Single 问题 / 选项 | Multiple 问题 / 选项 | GUI 可筛问题 / 原子答案 | Input 问题 |
|---:|---:|---:|---:|---:|
| 10 | 54 / 239 | 20 / 148 | 74 / 387 | 37 |
| 11 | 52 / 242 | 21 / 161 | 73 / 403 | 39 |

`decodeAdditionalConstraint.ts` 会把 GUI 选择全部连接成 AND。其多问卷分支在相邻条件间没有显式补空格，且角色/曲名直接插入双引号；批量抓取不应复刻这一 URL 序列化细节，而应直接生成带明确空格、使用官网原始名称的规范 DSL。译名归并应在下载后的规范化层完成，不能拿修订译名向官方接口查询。

## GraphQL 契约

统一端点：`https://touhou.vote/res-be/graphql`

三个结果页使用同一种匿名 GraphQL 文档形态，仅根字段不同：

```graphql
query ($query: String, $voteStart: DateTimeUtc!, $voteYear: Int!) {
  queryCharacterRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    global { ... }
    entries { ... }
  }
}
```

音乐和 CP 分别把根字段换成 `queryMusicRanking`、`queryCPRanking`。`query` 可省略；无条件页面实际不传该变量。当前本地抓虫把四个只读根字段合并为具名操作 `OptionCondition`：`queryGlobalStats`、`queryCharacterRanking`、`queryMusicRanking`、`queryCPRanking`。GraphQL 操作名只是客户端标签，不改变后端语义。

届次固定变量：

| 届次 | `voteYear` | `voteStart` |
|---:|---:|---|
| 10 | 10 | `2022-06-17T10:00:00.000Z` |
| 11 | 11 | `2023-12-29T10:00:00.000Z` |

### 排名全局字段

三个部门的 `global` 均为：

```text
totalUniqueItems, totalFirst, totalVotes,
averageVotesPerItem, medianVotesPerItem
```

### 角色条目字段

```text
rank, displayRank, name, voteCount, firstVoteCount,
firstVotePercentage, firstVoteCountWeighted, votePercentage, firstPercentage,
maleVoteCount, malePercentagePerChar, femaleVoteCount, femalePercentagePerChar,
nameJpn, characterType, characterOrigin, firstAppearance,
malePercentagePerTotal, femalePercentagePerTotal
```

### 音乐条目字段

```text
rank, displayRank, name, voteCount, firstVoteCount,
firstVotePercentage, firstVoteCountWeighted, votePercentage, firstPercentage,
maleVoteCount, malePercentagePerChar, femaleVoteCount, femalePercentagePerChar,
album, nameJpn, firstAppearance,
malePercentagePerTotal, femalePercentagePerTotal
```

### CP 条目字段

```text
rank, displayRank, cp { a, b, c },
aActive, bActive, cActive, noneActive,
voteCount, firstVoteCount, firstVotePercentage, firstVoteCountWeighted,
votePercentage, firstPercentage,
maleVoteCount, malePercentagePerChar, malePercentagePerTotal,
femaleVoteCount, femalePercentagePerChar, femalePercentagePerTotal
```

### 条件样本总体字段

官网后端的 `queryGlobalStats(query, voteStart, voteYear)` 可与排名放在同一只读请求中，当前抓取保存：

```text
voteYear, numVote, numChar, numMusic, numCp, numDoujin, numMale, numFemale
```

这些字段是解释条件分母所必需的，不能只保存排名行。

## 当前本地覆盖（审计时点）

| 届次 | 无条件角色/音乐/CP 条目 | 条件文件 | 结构完整 | 实际 GUI 原子答案 | 条件目录体量 |
|---:|---:|---:|---:|---:|---:|
| 10 | 239 / 595 / 790 | 390 | 390 | 387 | 34.66 MiB |
| 11 | 244 / 612 / 593 | 406 | 406 | 403 | 31.08 MiB |

每个条件文件均含 `queryGlobalStats` 和角色、音乐、CP 三个条件排名。多出的 3 个文件分别对应开放题 `21031`、`21051`、`21061` 的空白占位答案；两届的六个响应均为 `numVote=0` 且三个排名为空。建议：

- 原始层保留，作为“官方定义中的无效占位”证据；
- 在覆盖报告中标记 `excluded_non_gui_input_placeholder`；
- 不计入有效高级搜索条件数，也不进入数值分析。

## 建议的有限抓取范围

“完整”建议按以下层级验收，避免无意义的笛卡尔积：

1. **基础层（必须）**：每届无条件 `queryGlobalStats` 与三个完整排名，完整字段只保存一次。
2. **问卷原子层（必须）**：每个非空 Single/Multiple 答案单独作为条件；返回总体分母及三个部门的 `rank/displayRank/标识/voteCount/firstVoteCount`。CN10/11 此层已经完成。
3. **同部门关联层（必须）**：每个角色执行一次 `chars:[source]` 只取角色排名；每首音乐执行一次 `musics:[source]` 只取音乐排名。它可在官方全矩阵接口失效时无损重建共投计数，不必同时抓反方向。
4. **角色—音乐跨部门层（建议）**：若文章要分析角色—音乐关系，只做一个方向。角色数少于曲目数，优先对每个角色执行一次 `chars:[source]` 并只取音乐 `name/voteCount/firstVoteCount`；CN10 需 239 次、CN11 需 244 次，即可得到完整角色×音乐交集，反向查询是重复数据。
5. **本命层（按论题）**：`chars_first`、`musics_first` 只在明确分析“本命带来的差异”时抓；不要默认复制普通共投矩阵的全部组合。
6. **多条件层（定向）**：AND/OR/括号表达式只根据预先登记的研究假设抓取，并在 manifest 保存原始 DSL、规范 DSL、变量和目的。不要穷举任意两两或三重组合。
7. **CP 与三阶交互（定向）**：问卷原子层已经同时返回 CP 排名；角色→CP、音乐→CP、角色×音乐×问卷等高阶数据只有在具体论点需要时再抓。

条件排名中不必重复下载基础元数据、格式化百分比和图片。`votePercentage` 等比例可由条件分母和票数复算；如果研究确实需要“条件内再按性别拆分”的三阶交互，才为相应定向查询增加男女字段。

## 实现注意事项

- 指令模式 `q` 支持比 GUI 更丰富的 OR/括号表达式；不要用 URL `a` 的可枚举性推断 DSL 的全部空间。
- 页面把 `votePercentage` 的标题是否显示为“同投率”只绑定到 URL `a`，没有同时检查指令模式 `q`。因此命令模式下 UI 文案可能仍显示“票数占比”；分析应以查询条件与保存的分母为准，不以表头文本推断含义。
- 同一数组内的多个名字是 OR；若要计算两个对象同时入选，必须使用两个单元素规则并以 AND 连接。
- 官网条件使用官方中文名称精确匹配。原始层保留官方名称；用户维护的译名修复和同曲合并在规范化层应用。
- 无条件主榜、条件榜和共投矩阵应分别保存来源口径。不能把页面只显示的过滤结果误当作新的官方主榜，也不能把有限展示的关联图冒充完整矩阵。

## 未独立实测与历史届探针

- 本次源码审计确认了 DSL 的语法和 GUI 生成规则，但没有独立穷举验证所有多条件 AND/OR/括号组合；这类组合本身也没有有限全集。
- `votePercentage` 等比例字段的精确分母语义没有为每一种条件独立反推。数值分析应优先使用同一响应保存的 `queryGlobalStats` 和各榜 `global` 作为分母，并由本地程序复算。
- 2026-08-17 追加只读探针：GraphQL 对 `voteYear=5..9` 的 `queryGlobalStats` 均返回全零；同一请求中的 `voteYear=10` 正常返回 `numVote=25707`。第 9 届极简角色榜还返回 `No documents provided to insert_many`。因此现代 GraphQL 没有第 5–9 届历史数据，旧站高级搜索不能由该端点替代。

## 证据文件

CN10：

- `data_raw/cn_official/round_10/static/assets/AdvancedSearch.vue_vue_type_script_setup_true_lang-742fe348.js.map`
- `data_raw/cn_official/round_10/static/assets/decodeAdditionalConstraint-5d07289b.js.map`
- `data_raw/cn_official/round_10/static/assets/characterDetail-219345ed.js.map`
- `data_raw/cn_official/round_10/static/assets/MusicDetail-21bc1482.js.map`
- `data_raw/cn_official/round_10/static/assets/CoupleDetail-bde8ced8.js.map`
- `data_raw/cn_official/round_10/questionnaire/definition.normalized.json`
- `data_raw/cn_official/round_10/graphql/base.json`

CN11：

- `data_raw/cn_official/round_11/static/assets/AdvancedSearch.vue_vue_type_script_setup_true_lang-5a7fd4f0.js.map`
- `data_raw/cn_official/round_11/static/assets/decodeAdditionalConstraint-7c1b9997.js.map`
- `data_raw/cn_official/round_11/static/assets/characterDetail-7a3887a9.js.map`
- `data_raw/cn_official/round_11/static/assets/MusicDetail-50ca87bf.js.map`
- `data_raw/cn_official/round_11/static/assets/CoupleDetail-fbcdfb55.js.map`
- `data_raw/cn_official/round_11/questionnaire/definition.normalized.json`
- `data_raw/cn_official/round_11/graphql/base.json`

共同抓取实现与已有接口说明：

- `scripts_pipeline/crawl_cn_modern.py`
- `metadata/touhou_vote_v11_graphql.md`
- `data_raw/cn_official/round_10/round_manifest.json`
- `data_raw/cn_official/round_11/round_manifest.json`
