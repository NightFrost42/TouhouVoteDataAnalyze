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

## 日区与国区角色评论/投票理由

`crawl_character_comments.py` 抓取日区 JP3–22 和国区 CN1–11 的角色级公开文本。这里的“评论”按官网原字段保存：日区是角色投票评论，国区官网称为投票理由；不把理由改写成情绪标签，也不执行或渲染正文中的 HTML。它使用现有的 JP3–16 下载清单、CN1–9 本地角色详情和 CN10–11 本地角色排行作为实体目录，再按官方公开入口补抓正文；JP17–22 的静态 JavaScript 由同目录的 `crawl_jp_character_comments.mjs` 使用受限字面量解析器读取，CN10–11 使用公开的 `queryCharacterReasons` GraphQL 查询，不调用投票 token 接口。

默认运行完整范围（建议低并发、可断点续跑）：

```powershell
python .\scripts_pipeline\crawl_character_comments.py --workers 4
```

输出为 `data_raw/character_comments/<region>/round_XX/entities/*.json` 和压缩长表
`comments.jsonl.gz`；来源 URL、SHA-256、届次/角色覆盖和错误写入
`metadata/character_comments_manifest.json`、`metadata/character_comments_coverage.csv`。评论正文是公开用户提交文本，应视为不可信数据；展示到网页时必须按纯文本转义。可以用 `--jp-rounds 17-22`、`--cn-rounds 10-11` 只补指定范围，或用 `--refresh` 忽略实体缓存重新抓取。完整运行预计会产生大量文本，请先确认磁盘空间和站点访问许可。

抓取完成后运行 `process_character_comments.py`：

```powershell
python .\scripts_pipeline\process_character_comments.py
```

它会读取抓取清单，重新校验实体文件并生成 `data_processed/character_comments/comments.csv.gz`
（保留原文、来源和文本哈希，并增加字符数、脚本类型、链接/HTML 标记、空文本和精确重复标记）、
`entity_summary.csv`、`round_summary.csv`，以及 `analysis_results/character_comments/processing_summary.json`。
这些字段只描述文本结构和数据质量，不把关键词、长度或重复数解释成情绪、支持度或票数。

统一分析构建脚本会读取 `entity_summary.csv`，按地区/届次/角色名把摘要并入
`vote_explorer/data/analysis_character_metrics_all.csv`，并生成
`analysis_results/character_comments/role_by_round.csv`、`role_analysis.json` 和未匹配实体清单。
评论在系统中是公开理由/表达行为的描述性旁证；没有评论者与投票者的一一对应关系，不能把评论条数当成票数或评论者比例。

已有角色表可用 `python scripts_pipeline/build_vote_explorer_analysis_data.py --comments-only` 单独刷新评论列与审计清单。同名歧义、别名冲突或重复挂接保持 `ambiguous` 空值；来源错误为 `source_error`。逐届 `mean_entity_comment_chars` 为角色平均长度的等权均值（schema v2，替代旧列 `mean_comment_chars`），完整公式见[数据字典](../docs/network_analysis_data_dictionary.md#角色评论与投票理由)。


`build_vote_dataset.py` 离线读取 `data_raw/`、`data_processed/` 和已修订工作簿，生成 `datasets/votes_cn1-9_jp3-22/` 的统一长表，覆盖 CN1–11 与 JP3–22。CN10/CN11 的普通榜来自官方 GraphQL `graphql/base.json`；高级问卷条件、实体问卷和两两交叉表分别保留来源与缺陷审计，不把缺失接口结果补成 0。

同投指标的公式和状态由 `covote_metrics.py` 统一提供：完整 CN 四格行输出 raw counts、双向 conditional rate、独立基准、lift、cosine/Ochiai、Jaccard、PMI/NPMI、φ；JP 前列只保留官网可观察的 raw count、conditional rate 和 rate-ratio lift，完整 2×2 字段强制为空。`audit_covote_metrics.py` 独立重读原始 CN 矩阵和 JP 关联表，生成 `analysis_results/covote_metrics_audit.json` / `.md`；审计失败时不得把输出解释为完整矩阵。跨部门角色×曲子因两个部门的总体票数不同，也只输出条件率和 rate-ratio lift。

## 网络矩阵结构相关

`scripts_pipeline/analyze_matrix_correlations.py` 比较带标签的对称关系矩阵，并输出
`analysis_results/network_inference/matrix_correlations.csv` 与同目录的 `matrix_correlations_run_manifest.json`。默认比较
角色/音乐同投的 `raw_count`、`lift`、`cosine`，以及官方二人 CP 与角色同投；也会比较
CN1–11、JP3–22 固定范围内所有可用的相邻届同一矩阵指标。角色×音乐是二部矩阵，不会在没有明确投影定义时
与角色×角色或音乐×音乐矩阵直接相关。

矩阵先按 canonical 节点 ID 对齐，只提取严格上三角；对角线、自环、空白和未公布配对不参与，
真实的数值 0 会保留。`pair_count` 是两矩阵共同可观测的实际配对数，`complete_pair_matrix`
只有双方来源声明完整且共同节点的全部无序配对都有该指标时才为真。不完整的官方前列不会被
自动补成 0。Pearson/Spearman 的显著性使用同步置换一张矩阵的节点标签（行和列同一置换）
得到，不使用普通向量相关的渐近 p 值。**矩阵结构相关，不代表因果。**

例如用较小置换数做快速检查：

```powershell
python .\\scripts_pipeline\\analyze_matrix_correlations.py --permutations 200 --random-seed 20260929
```

运行清单记录输入分卷、输出哈希、节点摘要、随机种子、置换次数、共同可观测配对规则和缺失/完整性检查。

## MRQAP / QAP 对偶回归

`scripts_pipeline/mrqap.py` 对显式完整的无向角色同投矩阵运行逐届 OLS/LPM + QAP。连续因变量（默认 `lift`、`cosine`、`phi`）分别建模；二值关系（例如一个**显式提供且完整**的 `formed` 字段）单独标记为 `linear_probability`，不会把 CP 前列未出现的配对补成 0。普通回归的 `ordinary_p` 与节点置换/ Freedman–Lane 半偏置换得到的 `qap_p` 是两个不同字段，QAP 使用 studentized t 统计量和 +1 校正。

模块默认拒绝不完整矩阵以及同一组内完整/部分混合的输入。JP 官网关联前列只会在运行清单中作为排除组出现；结构元数据中的空白/`unknown` 不会转成 `false` 或 0。缺失控制变量会通过节点级完整子矩阵处理，以保持置换所需的节点结构；秩亏、常数预测变量和无完整案例会写入 `collinearity_diagnostic`，不会用伪逆伪造可解释系数。

默认输出为 `analysis_results/network_inference/mrqap_coefficients.csv`，同目录的 `model_run_manifest.json` 记录输入哈希、节点摘要、模型类型、随机种子、置换次数、置换方案、完整性检查和排除原因。生产数据中的 `stage` 当前尚未有已确认值，因此包含 `same_stage` 的公式可能明确返回 `no_complete_cases`；这不是“所有角色都不在同一关卡”。

直接对已经准备好的 dyad CSV 运行：

```powershell
python .\scripts_pipeline\mrqap.py --input .\path\to\complete_dyads.csv --continuous-metrics lift,cosine,phi --binary-metrics formed --permutations 1000 --random-seed 20260928 --permutation-scheme both
```

如需使用仓库同投表并自动连接结构/人气字段，省略 `--input`，使用默认的 `--covote`、`--structure` 和 `--metrics` 路径；只有显式存在的二值 Y 才会进入 LPM。清单可用 `python scripts_pipeline/model_run_manifest.py verify <manifest> --root .` 重新核验。


## 统一网络统计输出层

三个统计脚本的数值计算彼此独立：`network_hypothesis_tests.py` 输出非参数结构假设检验，`analyze_matrix_correlations.py` 输出矩阵相关，`mrqap.py` 输出 MRQAP/QAP 系数。它们的源表和各自运行清单保留在 `analysis_results/network_inference/`。如需把这些结果交给文章、审计或下游程序，运行统一适配器：

```powershell
python .\scripts_pipeline\network_inference_output.py --source-dir .\analysis_results\network_inference --output-dir .\analysis_results\network_inference\unified
```

适配器不重新计算效应量、p 值或校正值；它只校验并规范已有结果，写出：

- `hypothesis_tests.csv`：假设、效应量、原始 p、q、校正方法和有效/排除样本数；
- `matrix_correlations.csv`：矩阵对、Pearson/Spearman 相关、同步节点置换 p；
- `mrqap_coefficients.csv`：模型系数、QAP p、普通回归 p、置换方案和 complete-case 数；
- `sensitivity_scan.csv`：调用方实际提供的敏感性场景；没有运行时保留表头并在摘要中警告，不把空表解释为零效应；
- `analysis_summary.md`：从四张 CSV 自动汇总数据范围、缺失政策、指标解释、效应量、p/q 和警告；
- `model_run_manifest.json`：统一输入/输出 SHA-256、行数、字段、参数、来源运行清单和完整性检查；`figures/` 是可选展示目录。

统一表同时保留 `result_id`、机器字段、中文/日文显示名、canonical key、`feature_label_zh`/`feature_label_en`、status 和 source 字段。未知配对不会被补成 0；无完整案例、秩亏或来源未提供校正值会分别用显式状态/`adjustment_method=not_applied` 记录。字段契约见 `metadata/network_inference_output.schema.json`。删除 `figures/` 后，CSV、JSON 和 Markdown 仍包含全部可审计数字与运行参数；可用下面命令重新核验：

```powershell
python .\scripts_pipeline\model_run_manifest.py verify .\analysis_results\network_inference\unified\model_run_manifest.json --root .
```

摘要始终包含以下解释边界：共同投票不等于 CP 或原作关系；空白不等于真实 0；显著性不等于因果关系；不同届次和地区的投票规则可能不同；部分同投数据为公开关联列表而非完整矩阵。

## 标准社区检测（与连通分量聚类分开）


`scripts_pipeline/network_communities.py` 是可选的标准网络分析模块，不改变 `vote_explorer/analysis_engine.py` 中已有的“共同人数/lift 阈值 + 单链接连通分量”语义。当前实现了依赖 Python 标准库的加权 Louvain；Leiden 等其他算法尚未启用，命令行会对未支持算法失败关闭，不会静默改用另一种算法。

例如，对单个届次的角色同投完整矩阵运行：

```powershell
python .\scripts_pipeline\network_communities.py --round CN11 --scope character --algorithm louvain --weight-metric intersection_count --threshold 100 --resolution 1.0 --random-seed 20260801 --data-policy complete_matrix
```

使用 `--round all` 会发现节点表中的全部 CN/JP 届次，并写入
`analysis_results/network_communities/by_round/<round_label>/`；每个届次有独立的五件套和
`community_run_manifest.json`，根目录另有 `all_rounds_manifest.json`。没有已公开同投边的届次仍会
保留节点并输出孤立节点社区，不会把缺失关系补成 0。

所有网络分析的逐届来源配对数、完整矩阵行数、结果行数和不可用原因由
`scripts_pipeline/network_coverage.py` 汇总到 `analysis_results/network_coverage.csv` / `.json`。
早期有角色节点但无官方配对表的社群结果标记为仅含孤立节点，不代表无关系。

角色、音乐和跨部门三种 scope 可以分别写入不同目录，例如：
`--scope music --output-dir analysis_results/network_communities/music` 和
`--scope cross_department --output-dir analysis_results/network_communities/cross_department`。
批次 manifest 会列出同一 scope 的全部届次，即使该届次没有公开边。

跨部门角色×曲子网络使用 `--scope cross_department`，音乐内部网络使用 `--scope music`。`threshold` 是所选 `weight_metric` 的正权重下限；`--min-intersection-count` 是独立的共同人数下限。未公开的 JP 关系仍按右删失/未观测处理，不会补成 0；`--data-policy` 可选择 `observed`、`complete_matrix`、`published_leading_list` 或 `cross_department_conditional_only`。孤立节点来自当届指标表，保留在输出中。

每次运行写入 `analysis_results/network_communities/`：

- `community_assignments.csv`：逐节点的稳定社区 ID、独立连通分量参考 ID、算法参数和官方阵营隔离声明；
- `community_summary.csv`：社区规模、内部边/权重与 modularity 贡献；
- `node_centrality.csv`：加权/非加权度、PageRank、加权 betweenness、k-core 和 bridge score；
- `modularity_summary.csv`：modularity、度同配性、相对阈值图连通分量的 NMI，以及运行时间/峰值内存基准；
- `community_run_manifest.json`：输入/输出 SHA-256、Git/Python/软件版本、算法、权重指标、阈值、分辨率、随机种子、节点摘要、缺失配对政策和完整性检查。

社区 ID 是 `sha256([round_label + ':' + scope, sorted_member_node_ids])[0:16]`，不依赖 Louvain 内部临时编号；因此同一届次/范围与成员集合在不同运行中可追溯。`bridge_score` 定义为节点跨社区关联边权÷节点加权度；`NMI` 定义为社区分区与同一阈值观测图连通分量之间的 arithmetic `2I/(H1+H2)`。社区标签只表示网络结构，绝不能当作原作阵营、官方 CP 或原作阵营元数据的替代品；原作阵营仍只来自 `analysis_character_factions.csv`。

该模块明确不调用当前工作台的集中聚类 builder。空网络、孤立节点、单社区网络和重复/非法权重有独立测试；`modularity_summary.csv` 会记录 `runtime_seconds`、`load_seconds`、`algorithm_seconds` 和 `peak_memory_bytes`，用于大型网络运行基准。

## 网络统计运行清单

`scripts_pipeline/model_run_manifest.py` 写入一个 `model_run_manifest.json`。它与数据集构建用的
`manifest.json` 职责不同：前者描述一次模型运行，后者描述一套可分发数据集。字段和类型的机器可读契约见
`metadata/model_run_manifest.schema.json`。

清单会统一保存：输入/输出文件的相对路径、字节数和 SHA-256；分析版本、脚本、Python 与 Git
版本（包括工作区是否 dirty）；完整参数；随机种子、置换次数和检验尾部；节点集及其规范化 ID
摘要；配对纳入、去重、自环和缺失配对规则；以及覆盖、缺失、重复、非法值和警告等数据完整性
结果。节点 ID 会先转成非空字符串并排序，再对紧凑 UTF-8 JSON 列表计算 `ids_sha256`；因此节点
遍历顺序不会改变清单摘要。文件哈希和节点摘要由 writer 重新计算，不应把调用方传入的旧哈希当作
证据。缺失配对必须明确写入规则，不能把未公开关系默认为 0。

最小调用方式（建议把清单放在对应分析目录内）：

```python
from pathlib import Path
from scripts_pipeline.model_run_manifest import write_model_run_manifest

write_model_run_manifest(
    Path("analysis_results/network/model_run_manifest.json"),
    root=Path("."),
    analysis="character_covote_network",
    analysis_version="1.0.0",
    inputs=[{"path": "vote_explorer/data/analysis_covote_pairs_all.csv", "role": "pair_source"}],
    outputs=[{"path": "analysis_results/network/edges.csv", "role": "edges"}],
    parameters={"round": "CN11", "min_count": 100},
    random_seed=20260801,
    permutations=20_000,
    tail="two-sided",
    node_set={
        "entity_type": "character",
        "source": "analysis_character_metrics_all.csv",
        "selection_rule": "rank <= 100",
        "ids": ["reimu", "marisa"],
    },
    pair_inclusion={
        "rule": "intersection_count >= 100",
        "missing_pair_policy": "exclude_and_report",
    },
    data_integrity={
        "status": "passed",
        "checks": [{"name": "round_coverage", "ok": True}],
    },
)
```

读取并重新核验文件：

```python
from scripts_pipeline.model_run_manifest import read_model_run_manifest, verify_model_run_manifest

manifest = read_model_run_manifest("analysis_results/network/model_run_manifest.json")
verification = verify_model_run_manifest(
    manifest,
    root=".",
)
if not verification["ok"]:
    raise RuntimeError(verification)
```

也可以执行 `python scripts_pipeline/model_run_manifest.py validate <path>` 或
`python scripts_pipeline/model_run_manifest.py verify <path> --root <workspace>`。验证会分别列出
每个输入/输出的存在性、期望/实际哈希与大小。Git 工作区不干净不会阻止写入，但会记录为
`code.git_dirty: true`，由报告使用者决定是否接受该运行。

## 角色对网络假设检验

`scripts_pipeline/network_hypothesis_tests.py` 读取 `analysis_covote_pairs_all.csv`、角色对结构特征和结构元数据，按 `metadata/network_hypothesis_tests.json` 中的表达式生成观察组/对照组。它输出 Mann–Whitney U、Cliff’s δ、percentile bootstrap CI，以及角色节点属性置换的 Monte Carlo p 值，并在默认的区域×届次×指标族内做 Holm 校正：

```powershell
python .\scripts_pipeline\network_hypothesis_tests.py
```

结果写入 `analysis_results/network_inference/hypothesis_tests.csv`，同目录的 `hypothesis_tests_manifest.json`（`model_run_manifest` 格式，避免与其他网络分析运行的清单重名）记录输入哈希、配置、seed、置换次数、节点/配对纳入规则和完整性计数。表达式可以使用 `same_stage == 1` / `same_stage == 0` 这类通用结构特征；当前 `stage` 尚无已验证值，默认配置因此保留该假设的不可检验结果，并使用已有的首登作品、角色类型、来源组和 region 特征作为可运行示例。结果行明确标记 `exploratory`/`confirmatory`，默认均为 exploratory。

CN10/11 的 `complete_matrix` 行保留官方显式零；JP 关联前列等 `partial_matrix_observed_only` 行只比较已发布的角色对。未发布、删失的角色对不会被枚举、补零或进入置换样本。依赖完整四格的 share、Jaccard、cosine、PMI/NPMI、φ 等指标在部分矩阵中保持不可检验；空组、ties、全相同值和单元素组以空统计量或有限的零宽区间明确输出，而不是用独立样本渐近 p 值替代节点置换检验。

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
