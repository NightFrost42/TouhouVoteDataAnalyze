# 中文投票第 1–11 届高级搜索能力审计

审计日期：2026-08-17  
范围：`touhou.vote` 官方结果站；重点核对第 1–9 届旧站，并与第 10、11 届现代站对齐。  
排除：评论、投票理由、图片、字体、开放文本原文和个人票记录。  

## 结论

1. 第 1–4 届公开结果 UI 没有“任意条件重算投票样本”的高级搜索。它们提供的是固定排名变体、预汇总投票群字段、固定实体详情及有限共投展示，不能伪装成可任意筛选的条件榜。
2. 第 5–9 届公开结果 UI 确实提供服务器端样本筛选，输出目标只有角色榜和音乐榜：
   - 按一个问卷答案筛选投票人；
   - 按是否投过一个角色/音乐筛选投票人，并可限定为本命；
   - 官网 UI 一次只接受一个样本条件，没有 AND/OR 组合。
3. 第 5–9 届实体条件的可选源也只有角色、音乐，不包括作品、游戏或 CP。每个实体应分别保存 `votetrue=0`（投过）和 `votetrue=1`（本命）两个官方原子条件。
4. 第 5–9 届的 `min` / `max` 只是服务器端按结果行票数截取显示范围，不改变投票人样本；它可以从完整条件榜本地重现，不需要枚举。
5. 第 10、11 届使用 GraphQL 条件 DSL，支持角色、角色本命、音乐、音乐本命、问卷答案以及任意 AND/OR/括号。组合空间没有有限上界；“完整覆盖”应定义为完整保存所有 GUI 原子条件及接口契约，而不是穷举任意布尔表达式。
6. 现代 GraphQL 虽语法上接受 `voteYear=5..9`，但没有旧届数据，不能用来绕过旧站的慢条件页。

## 分类口径

| 分类 | 含义 | 是否属于本次高级条件榜 |
|---|---|---|
| `server_side_sample_filter` | 改变投票人集合，由服务器重算排名 | 是 |
| `display_variant` | 同一批结果的预设列、排序、权重或行范围 | 否；保存一份完整数值即可 |
| `client_only_filter` | 浏览器对已返回行做关键词/票数过滤 | 否 |
| `detail_aggregate_api` | 固定实体的性别、地区、时间、问卷分布 | 不是高级搜索，但属于应抓的附加数值 |
| `crossvote` | 共投边、同投率或有限共投排行 | 单独归档，不混入条件榜 |

## 逐届能力矩阵

| 届次 | 服务器样本高级搜索 | 公开能力与结论 |
|---:|---|---|
| 1 | 无 | 角色/音乐 `step=1..4` 是票数、本命数、本命率、本命权重显示变体；角色 `step=5` 是前 500 组共投；固定实体 JSON 详情另算 `detail_aggregate_api`。 |
| 2 | 无 | 角色/音乐 `s=1/2/3` 是详表、往届对比、投票群详表；作品 `s=1..4` 是详表、对比、玩家情况、作品角色对比；`?m=j&t=...&i=...` 是固定实体详情。 |
| 3 | 无 | 与第 2 届同构；角色/音乐公开目录仅列 `s=1/2/3`，三页分别为详表、往届对比、投票群详表。 |
| 4 | 无 | 角色/音乐 `t=simple/full/paper` 均是固定结果表；`t=paper` 是含男女票率及“偏原作/偏二次”等列的投票群表，只有表头排序，没有条件表单或样本重算。 |
| 5 | 有 | 角色/音乐条件榜；58 个可选问题；实体源 203 个角色、491 首音乐。另有问卷双变量交叉和固定实体附加 API。 |
| 6 | 有 | 与第 5 届同构；58 个可选问题；实体源 215 个角色、518 首音乐。 |
| 7 | 有 | 与第 5 届同构；58 个可选问题；实体源 218 个角色、552 首音乐。 |
| 8 | 有 | 与第 5 届同构；58 个可选问题；实体源 227 个角色、569 首音乐；新增阈值化共投图 API。 |
| 9 | 有 | 与第 5 届同构；59 个可选问题；实体源 229 个角色、571 首音乐；有阈值化共投图 API。 |
| 10 | 有 | GraphQL DSL；74 个 GUI 可筛问题、387 个有效答案原子条件；角色/音乐/CP 三榜均可按条件重算。 |
| 11 | 有 | GraphQL DSL；73 个 GUI 可筛问题、403 个有效答案原子条件；角色/音乐/CP 三榜均可按条件重算。 |

第 1–4 届的“无”特指公开 UI 和公开结果路由没有 `server_side_sample_filter`。它不否认这些届次已有丰富的固定汇总数据；这些汇总仍应照常落盘。

## 第 1–4 届反证

### 第 1 届

角色目录只暴露：

```text
index.php?mod=chara&step=1
index.php?mod=chara&step=2
index.php?mod=chara&step=3
index.php?mod=chara&step=4&w=0..5
index.php?mod=chara&step=5
```

缓存页面的自述分别是票数排行、本命数排行、本命率排行、本命加权排行和角色同投排行。所有结果页均无表单、选择框或输入框。`step=5` 明确只显示前 500 组（含并列），属于 `crossvote`，不是任意筛选。音乐目录只有 `step=1..4`。

### 第 2、3 届

第 2 届角色和音乐目录仅列 `s=1/2/3`，对应票数排行详表、往届对比表、投票群详表；第 3 届官网在线页面逐页核对后完全同构。结果页只有固定 `t` 子排序及 `?m=j&t=<类型>&i=<ID>` 实体详情链接，没有筛选表单、下拉框、输入框或 Ajax 样本查询。

### 第 4 届

`t=paper` 容易被误认为按问卷筛榜，实测并不是。角色页自述为“角色部门的投票群表”，音乐页自述为“音乐部门的投票群表”；表中同时提供男性、男性率、女性、女性率、偏原作、偏二次等固定列。公开链接只切换 `s=male/female/mratio/fratio` 排序。页面的表单、下拉框、输入框和 Ajax 请求数均为 0，因此分类为 `display_variant`。

## 第 5–9 届高级搜索契约

### 1. 问卷答案条件

角色结果：

```text
GET https://touhou.vote/vN/?m=chara&type=simple&quest=<问题token>&item=<答案token>
```

音乐结果：

```text
GET https://touhou.vote/vN/?m=music&type=simple&quest=<问题token>&item=<答案token>
```

问题目录内嵌在两页的 `var questlist = [...]`。答案目录由官网接口返回对象映射：

```text
GET https://touhou.vote/vN/api.php?action=advice&object=item&text=<问题token>
```

例如第 9 届“您的性别”返回 `{"1":"男性","2":"女性"}`。结果页由服务器重算，页面会写明“过滤后票数排行简表”和当前过滤条件；不能把它当浏览器本地隐藏行。

### 2. 是否投过指定实体

角色或音乐结果页使用同一参数：

```text
GET https://touhou.vote/vN/?m=<chara|music>&type=simple
    &votetype=<chara|music>&voteid=<实体ID>&votetrue=<0|1>
```

- `votetrue=0`：投过该实体；
- `votetrue=1`：只取把该实体选为本命的投票者；
- 输出目标 `m` 只有 `chara`、`music`；
- 条件源 `votetype` 也只有 `chara`、`music`。

实体目录接口：

```text
GET https://touhou.vote/vN/api.php?action=advice&object=list&text=chara
GET https://touhou.vote/vN/api.php?action=advice&object=list&text=music
```

官网枚举计数如下：

| 届次 | 角色实体 | 音乐实体 | 两种本命口径 × 两个输出目标所需页面数 |
|---:|---:|---:|---:|
| 5 | 203 | 491 | 2,776 |
| 6 | 215 | 518 | 2,932 |
| 7 | 218 | 552 | 3,080 |
| 8 | 227 | 569 | 3,184 |
| 9 | 229 | 571 | 3,200 |

表中最后一列只计算实体原子条件，尚未加入问卷答案条件页。

### 3. `min` / `max`

页面支持：

```text
&min=<最小票数>&max=<最大票数>
```

它只限制结果中显示的条目票数范围。页面 JavaScript允许它附加在问卷或实体条件之后，但它不增加新的投票人条件，完整条件榜下载后可本地复现。特别注意：旧站 `filterBtn` 在已有实体条件上附加 `min/max` 时没有继续带上 `votetrue`，因此也不能拿这个组合 URL 推断本命口径。

### 4. 组合语义

第 5–9 届 UI 每次只选择一个问卷答案或一个实体；选择问卷/实体会清除其他样本条件。没有公开的 AND、OR、括号或否定语法。完整抓取应枚举官方原子条件，不应自行制造未由 UI 提供的组合参数。

## 第 5–9 届其他分析相关 API

这些数据不是角色/音乐高级条件榜，但属于用户要求的附加数值，应分目录保存。

### 问卷问题 × 问题交叉表

第 5–9 届均提供：

```text
POST api.php?action=make&object=votepaper&text=paper
body: quest1=<问题token>&quest2=<问题token>
```

响应是两个问卷问题的答案交叉表。它与“按某答案筛角色/音乐榜”是两类数据，不能互相替代。去重抓取时可规范化问题对顺序，但必须保留行轴、列轴和原始请求参数。

### 固定实体附加分布

第 5–9 届 `info.js` 同构：

```text
GET  api.php?action=make&object=votedate&text=<type>&id=<id>
GET  api.php?action=make&object=votesex&text=<type>&id=<id>
GET  api.php?action=make&object=votegeo&text=<type>&id=<id>
POST api.php?action=make&object=votepaper&text=<type>&id=<id>
     body: paper=<问题token数组>
```

这些接口给出固定实体投票者的时间、性别、地区和问卷分布，分类为 `detail_aggregate_api`。问卷总览页另使用 `votedate/votesex/votegeo` 和分组 `votepaper` 请求。

### 第 8、9 届共投图

```text
POST api.php?action=make&object=votecrossvote
     &text=<chara|music>&filter=<名次阈值>&rate=<相关阈值>
```

响应 JSON 的边包含源/目标、两端票数、同投票数、同投率和相关统计，数值应保存，图像无需保存。当前只确认官网默认阈值和少量扩展阈值；`filter=0&rate=0` 返回字面量“错误make”，所以该接口不能宣称是完整共投矩阵。

## 第 10、11 届衔接

现代站详细契约见 `reports/cn_modern_advanced_ui_audit.md`。与旧站的核心差异：

- 条件通过 GraphQL `query: String` 传入；
- `chars`、`chars_first`、`musics`、`musics_first` 和问卷答案都是真正的服务器样本条件；
- 一个 GraphQL 请求可以同时保存条件总体及角色、音乐、CP 三榜；
- `keyword/searchRange/minCount/maxCount` 只是浏览器本地结果过滤；
- 任意 AND/OR/括号组合理论上无限，不能穷举。

按当前“凡官网高级搜索原子条件都抓”的口径，第 10、11 届还应分别枚举所有角色/角色本命、音乐/音乐本命和问卷答案原子条件；条件响应保留总体分母与三榜计数即可，基础元数据无需每次重复。

## 现代 GraphQL 历史届探针

对 `https://touhou.vote/res-be/graphql` 发出同一个 `queryGlobalStats` 请求，使用 `voteStart=1970-01-01T00:00:00.000Z` 以避免漏掉任何早期记录：

| `voteYear` | `numVote` | `numChar` | `numMusic` | `numCp` |
|---:|---:|---:|---:|---:|
| 5 | 0 | 0 | 0 | 0 |
| 6 | 0 | 0 | 0 | 0 |
| 7 | 0 | 0 | 0 | 0 |
| 8 | 0 | 0 | 0 | 0 |
| 9 | 0 | 0 | 0 | 0 |
| 10（同请求校验） | 25,707 | 23,518 | 17,442 | 17,383 |

第 9 届 `queryCharacterRanking` 进一步返回内部错误 `No documents provided to insert_many`。因此端点只是接受旧 `voteYear` 参数，并未保存第 5–9 届历史文档。

## 旧站性能与完整抓取风险

第 9 届“性别=男性”的音乐条件榜首次实测约 55 秒完成，返回 529 条音乐行；页面前置输出：

```text
Warning: file_put_contents(...cache...): failed to open stream: Permission denied
```

对完全相同 URL 串行刷新，约 58 秒后浏览器命令仍超时，随后页面才完成，并再次出现同一缓存写入警告和 529 条结果。说明当前旧站缓存没有生效。若所有实体原子条件都接近这一耗时，单是第 5–9 届实体条件页就达到十天量级的串行请求时间。

这不是删减条件的理由，但抓取实现必须具备：长超时、严格断点续跑、逐响应落盘、失败重试上限、可审计 manifest 和低并发/串行节流。不能在内存中攒完整届次后一次性写盘，也不能因超时把尚未请求的条件标记为“官网无数据”。

## 证据

第 1 届：

- `data_raw/cn_official_legacy/round_01/raw/pages/chara/index.html`
- `data_raw/cn_official_legacy/round_01/raw/pages/chara/mod_chara__step_1.html`
- `data_raw/cn_official_legacy/round_01/raw/pages/chara/mod_chara__step_5.html`
- `data_raw/cn_official_legacy/round_01/raw/pages/music/mod_music__step_4__w_2.html`

第 2、4 届：

- `data_raw/cn_official_legacy/round_02/raw/pages/chara/m_1__s_1.html`
- `data_raw/cn_official_legacy/round_02/raw/pages/chara/m_1__s_3.html`
- `data_raw/cn_official_legacy/round_02/raw/pages/music/m_2__s_3.html`
- `data_raw/cn_official_legacy/round_04/raw/pages/chara/index.html`
- `data_raw/cn_official_legacy/round_04/raw/pages/paper/index.html`

第 3 届在线核验 URL：

- `https://touhou.vote/v3/?m=1`
- `https://touhou.vote/v3/?m=1&s=1`
- `https://touhou.vote/v3/?m=1&s=2`
- `https://touhou.vote/v3/?m=1&s=3`
- `https://touhou.vote/v3/?m=2`

第 5、9 届本地源码（第 6–8 届官网同页逐一核对为同构）：

- `data_raw/cn_official_legacy/round_05/raw/pages/chara/m_chara__type_simple.html`
- `data_raw/cn_official_legacy/round_05/raw/pages/music/m_music__type_simple.html`
- `data_raw/cn_official_legacy/round_09/raw/pages/chara/m_chara__type_simple.html`
- `data_raw/cn_official_legacy/round_09/raw/pages/music/m_music__type_simple.html`
- `data_raw/cn_official_legacy/round_05/raw/scripts/info.js`
- `data_raw/cn_official_legacy/round_05/raw/scripts/paperinfo.js`
- `data_raw/cn_official_legacy/round_09/raw/scripts/info.js`
- `data_raw/cn_official_legacy/round_09/raw/scripts/paperinfo.js`
- `data_raw/cn_official_legacy/round_08/raw/scripts/crossvote.js`
- `data_raw/cn_official_legacy/round_09/raw/scripts/crossvote.js`

