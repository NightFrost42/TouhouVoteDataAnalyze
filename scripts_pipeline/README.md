# 可复算的数据流水线

本目录保存文章核查所用的维护中爬虫、规范化和分析程序。程序把官方原始响应写入
`data_raw/`，把统一字段写入 `data_processed/`，把计算结果写入
`analysis_results/`，并把来源、哈希和覆盖信息写入 `metadata/`。

## 日文官方数据

`crawl_jp_official.mjs` 会从 `https://toho-vote.info/` 发现当前版本的模块。默认抓取
第17—22回的总体问卷、逐实体角色/曲子/作品数据和官方关联数据；第21、22回作为较新的
独立届次保留。详情模块中的大段公开评论正文不保存，只保留来源 URL 和 SHA-256；问卷模块
中的官方反馈会保留。

`analyze_social_triangulation.py` 使用已保存的第21回汇总和详情字段，复算 3/2/1 与旧版
2/1 角色计分的反事实结果，整理问卷分母并统计少量开放反馈主题。输出位于
`analysis_results/social_triangulation/`；关键词计数只用于发现主题，不能当作意见占比。

`analyze_community_poll_alignment.py` 规范化已保存的 Bilibili 搜索快照，为中日角色历史增加
考虑候选池的名次百分位，并与整理后的 X/Pixiv/Bilibili 事件时间线连接。它会在
`analysis_results/community_poll_alignment/` 下分别输出日区平台/日区投票、中文区平台/中文区
投票以及明确标注的跨区表。平台指标与投票分开保存，不能相加为综合人气分数。

示例（PowerShell）：

```powershell
& '<bundled-node-path>\node.exe' .\scripts_pipeline\crawl_jp_official.mjs
```

只有在明确进行诊断时才使用 `--detail-rounds` 限定届次。完整复算应保持默认设置，避免历史
届次悄悄缺少条件问卷或实体关联记录。

## 中文区与统一投票数据

`build_vote_dataset.py` 离线读取 `data_raw/`、`data_processed/` 和已修订工作簿，生成 `datasets/votes_cn1-9_jp3-22/` 的统一长表，覆盖 CN1–11 与 JP3–22。CN10/CN11 的普通榜来自官方 GraphQL `graphql/base.json`；高级问卷条件、实体问卷和两两交叉表分别保留来源与缺陷审计，不把缺失接口结果补成 0。

`build_vote_explorer_analysis_data.py` 生成 `vote_explorer/data/` 的查询器分析表，包含 CP/组合、角色×音乐同投、问卷关联以及角色/曲子交叉数据。运行时会按地区和届次使用各自的实体问卷题目与选项，避免中文区和日文区同名选项互相覆盖。

超过 GitHub 单文件限制的 CSV 使用 `split_large_files.py` 分卷。完整重建后构建脚本会自动执行：

```powershell
python .\scripts_pipeline\split_large_files.py --all --replace
```

分卷文件每卷都保留表头，并在同目录写入 `.parts.json` 校验清单。查询器和分析构建脚本会自动读取分卷；需要恢复完整 CSV 时执行：

```powershell
python .\scripts_pipeline\split_large_files.py --all --merge
```

## 同人曲投票窗口

`crawl_thwiki_arrangement_counts.py` 只抓取 THBWiki 原曲的聚合计数和精确发售日分布，不下载曲目明细。它生成半年统计、JP 投票窗口和中文区投票窗口：

- `original_song_arrangement_counts_jp_vote_windows.csv`：JP3–22 独立日区投票日历；
- `original_song_arrangement_counts_cn_vote_windows.csv`：CN2–11 独立中文区投票日历；CN1 仅作为首届基线，不输出伪造的届间增量。

两个窗口表都同时提供届间新增、截至投票结束累计和抓取时点总数。CN/JP 同编号届次不会交叉套用时间窗口。该脚本支持从 `metadata/.thwiki_arrangement_counts_checkpoint.json` 断点恢复；断点和队列状态属于本机文件，已加入 `.gitignore`。

## 一键控制与持久配置

工作区根目录提供三个可双击入口：

- `启动爬取并打开控制台.cmd`：打开本机状态面板，并按上次保存的配置启动或恢复队列；重复点击不会启动第二个队列。
- `打开爬取控制台.cmd`：只打开面板，不改变队列状态。
- `停止爬取.cmd`：写入安全停机信号，并只终止元数据中精确记录的当前阶段子进程。失败时窗口会保留以显示原因。

控制台配置直接、原子地保存在 `metadata/data_crawl_queue.json`，关闭面板或重启电脑后仍会保留。`cn_legacy_advanced` 和 `cn_legacy_remaining` 分别记忆起始并发、每批请求数、正常批间冷却、三项对应护栏、请求重试数、请求超时、瞬时错误阈值，以及“自动恢复加速”开关。护栏默认是并发 10、每批 30、正常冷却 3 秒，均可在面板中修改；为避免误配置，程序仍保留 32、300、60 秒的绝对安全上限，且起始值不能超过对应护栏。自动调速会在稳定窗口后逐步探索到当前配置的护栏；如果单并发曾因 504 把冷却抬高，连续约 90 秒健康结果后会自动按约 20%（每次最多 2 秒、按 0.25 秒量化）试探更快速度，试探失败立即回到上一稳定冷却，多并发则使用更保守的 0.25 秒步长。同一抓取内容发生确认的 504 熔断后，已降低的安全并发上限和已提高的安全冷却下限会跨自动重试保留；切换到下一类抓取内容时二者都重置，再从面板配置探索。关闭自动恢复加速后，并发、每批请求数和冷却严格使用面板保存值，网络重试与熔断仍生效，但程序不会暗中改速。面板的“重新测速（恢复配置上限）”会安全停止当前阶段、保留文件/哈希/断点，清除该阶段的临时学习值，再从配置上限重新探索；其他阶段的学习档案不受影响。运行中保存不会改变当前子进程，参数会在后续阶段、重试或下次队列启动时生效；“保存并安全重启”会先停止当前子进程，再以哈希断点恢复，因此已验证成功的数据不会重抓。

面板每秒读取一次数值进度，并按最近完成结果的实际平均耗时计算当前子阶段的预计剩余时间；不会用固定 5 秒窗口放大短时波动。阶段切换、断点恢复或计数回退时会自动重新取样。该时间不包含尚未开始的后续队列阶段。队列总览、整套计划内容和速度配置均可折叠；折叠摘要仍保留当前阶段/项目及已保存速度，计划内容在固定高度滚动框中按待执行、进行中、已完成着色。

“抓取内容列表”会解析当前 attempt 日志中的每一条 `[vN ...] 总数 resources; cached=... local=... network=... workers=...` 汇总行，按届次显示入口、问卷目录、条件排行和两两关联表，并高亮当前子阶段。国区剩余阶段启用了 `--reuse-local-workbooks`：只有经固定 SHA-256、表头和数据行校验的 `TouhouVote_cn.xlsx` / `TouhouVote_music_cn.xlsx` 才会替代国区第1届角色/音乐的 step=2、3、4 重复排序视图；step=1 的实体发现、详情、问卷、时间/地域、关联投票和高级搜索仍然网络抓取。替代证据单独写入 `metadata/cn_legacy_local_source_manifest.json`，不会混入官方 HTTP manifest，面板会把本次实际替代数量显示为 `local`；历史替代记录只供离线重建核验，不会让普通或强制刷新运行误报为本次已使用。下方任务队列总览按配置顺序列出全部任务，并分别标注“网络抓取 / 数据整理 / 完整性校验 / 覆盖汇总”以及待执行、运行中、等待重试、已完成、失败或安全停止状态。安全重启后，控制台会先显示“正在初始化或恢复断点”；上一 attempt 的 100% 进度不会再被误显示为本次阶段完成。日志卡片的“复制”按钮会复制当前显示内容，轮询刷新遇到用户选区时会暂缓替换文本。

离线整理生成的 `datasets/votes_cn1-9_jp3-22/cn_entity_inventory.csv` 是 CN1–9 的逐实体核对表：它把详情索引、普通投票榜、CN5–9 高级条件结果、CN2–4 详情页群体统计和 CN5–9 item API 文件用统一的 `entity_key` 连接。详情抓取项也会在 `processed/details/index.csv` 和 `processed/item_apis/index.csv` 中带上同一键，因此缺少的排名或问卷资料可以按实体逐项定位；CN1–4 没有后期高级搜索 API 时会明确标为官方未提供，不会伪造高级结果。

瞬时网络错误会自动降低在途并发、增加冷却，并在连续成功结果达到稳定窗口后逐步探测恢复更高速度，直到用户配置的并发护栏。新内容在尚未失败时冷却可逐步降到 0.25 秒；一旦某个速度造成确认失败，之后的成功恢复不会再次越过该内容已学习的安全冷却下限。降到单并发恢复时，面板显示的当前冷却会作用于每一次真实 HTTP 请求起始（包括同一项目的内部重试），不再等满 30 项才等待；并发大于 1 的降级状态则每完成一个当前并发波就冷却一次。恢复冷却可临时超过普通护栏，但仍受 60 秒绝对上限约束。达到配置阈值后立即打开熔断，收尾在途请求，队列等待下一次恢复探测；再次启动只补失败和缺失项。

国区第 10–11 届现代 GraphQL 高级搜索和实体问卷阶段也使用同一套自适应速度控制：`--workers`、`--request-limit`、`--batch-pause` 及其三项 ceiling 会限制起始并发和请求间隔，稳定成功后逐步加速，遇到 429/5xx/网络超时则自动降速并保留断点。同一内容列表跨届次继续抓取时沿用已验证速度，不会在 round 切换时重置；只有切换到新的内容列表才会建立新的探索边界。速度学习档案写入 `metadata/cn_modern_adaptive_profiles.json`，按队列阶段隔离；关闭 `adaptive_tuning` 时仍保留重试和熔断保护，但严格使用配置值。

也可在命令行查看或控制：

```powershell
python .\scripts_pipeline\data_crawl_control.py status
python .\scripts_pipeline\data_crawl_control.py start
python .\scripts_pipeline\data_crawl_control.py stop --timeout 120
```

控制逻辑不会按进程名枚举或终止程序。新版队列会记录 PID、进程创建时间和可执行文件路径，停机时在同一个 Windows 进程句柄上完成身份核验；旧版队列若缺少身份字段，只会收到安全停止信号，不会根据裸 PID 强制终止进程。
