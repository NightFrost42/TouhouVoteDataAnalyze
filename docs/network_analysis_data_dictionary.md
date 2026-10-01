# 网络分析数据字典

阅读本页时先选具体文件，再按“地区 + 届次 + 范围/配对类别 + 来源状态”定位记录。空值表示没有足够证据或该计算未定义，绝不自动解释为 0。路径均相对仓库根目录；数据范围及运行清单见 [复现指南](network_analysis_reproducibility.md)，解释限制见 [方法说明](network_analysis_methodology.md)。

## 同投原表

`vote_explorer/data/analysis_covote_pairs_all.csv`（或其 `.parts.json` 所列分卷）每行是同届同部门的一对实体。来源：CN10–11 官方角色/音乐完整矩阵；JP11–22 官网角色/音乐公开关联前列。其他届次不生成配对行；逐届类别详见 `vote_explorer/data/analysis_data_manifest.json > covote_coverage`。`analysis_character_music_covote_all.csv` 是角色—音乐二部关系，须独立读取其状态和分母。两个文件不是 CP 榜。

| 字段 | 含义和计算口径 |
|---|---|
| `region`, `round`, `round_label`, `pair_category` | 地区、小写数字届次、显示届次（如 CN11）、角色/音乐类别；跨部门文件由角色和音乐端字段定义。 |
| `name_a`, `name_b`, `name_a_cn`, `name_b_cn`, `canonical_a`, `canonical_b`, `canonical_pair_key` | 原名、中文显示名、规范身份和无向配对键；不能只靠显示名合并不同实体。 |
| `rank_a`, `rank_b` | 两端在本届的官方名次；空值不是未入榜。 |
| `source_type`, `source_path`, `source` | 上游来源类型与路径；结合 manifest 的输入哈希核对。 |
| `data_completeness` | `complete_matrix` 为明确完整矩阵；`official_published_leading_list` 为仅公布前列；`not_available` 只见覆盖清单。 |
| `censoring_status` | `not_censored`、`right_censored_by_official_list`、`not_observed` 分别为完整、列表外未知、无来源。 |
| `complete_pair_matrix` | 布尔值，表示所声明实体宇宙的配对矩阵完整；不能仅由有若干行推断。 |
| `metric_status` | `exact_complete_2x2` 才有核验四格；`official_published_leading_list` 只有公开字段；`conflicting_published_directions` 表示两个公布方向冲突，保留冲突而不任取其一。 |
| `directions_found` | 从来源中实际找到的公布方向数，不是投票人数。 |
| `count_a`, `count_b`, `ballots` | 两端选择人数和同一完整选票宇宙总数；完整四格时 `count_a=m00+m10`、`count_b=m00+m01`、`ballots=m00+m01+m10+m11`。部分来源的空值不可反推。 |
| `intersection_count`, `raw_count` | 共同选择人数 `m00`；JP 只保留公布的已观测计数。 |
| `raw_count_a_to_b`, `raw_count_b_to_a` | 各公布方向记录的共同人数；若两个方向冲突，以 `metric_status` 提醒，勿强行视作相同。 |
| `m00_both_selected`, `m01_b_only`, `m10_a_only`, `m11_neither_selected` | 完整四格的两者都选、仅 B、仅 A、都未选；只在 `exact_complete_2x2` 填。 |
| `conditional_rate_a_to_b`, `direction_a_to_b` | `P(B|A)=m00/count_a`；后者是兼容别名。部分列表仅引用官网公布的方向值。 |
| `conditional_rate_b_to_a`, `direction_b_to_a` | `P(A|B)=m00/count_b`；后者是兼容别名。两方向分母不同，不应期待数值相等。 |
| `conditional_rate` | 来源行的默认公布方向条件率；读 A/B 方向时优先使用显式方向列。 |
| `share` | 完整同部门矩阵的共同选择份额 `m00/ballots`；不完整或不同选票宇宙不计算。 |
| `baseline_count`, `excess_count` | 完整四格的独立基准 `count_a*count_b/ballots` 及 `m00-baseline_count`；不是因果上的“额外票”。 |
| `lift`, `lift_a_to_b`, `lift_b_to_a`, `lift_basis` | 完整四格 `lift=m00/baseline_count=P(A,B)/(P(A)P(B))`；JP 前列按已公布条件率/总体率计算，`lift_basis` 标明口径。方向列沿来源方向，不能把不同 basis 混排。lift 不是稳定性或置信度。 |
| `cosine`, `ochiai` | 完整四格 `m00/sqrt(count_a*count_b)`；同一个 Ochiai/余弦值。部分列表留空。 |
| `jaccard` | 完整四格 `m00/(count_a+count_b-m00)`。 |
| `pmi`, `pmi_nats` | 完整四格自然对数 `ln(lift)`；基准为 0 或共同份额为 0 时留空。 |
| `npmi` | 完整四格 `pmi/(-ln(share))`，要求 `0<share<1`。 |
| `phi` | 完整四格 `(m00*ballots-count_a*count_b)/sqrt(count_a*count_b*(ballots-count_a)*(ballots-count_b))`；零分母留空。 |
| `asymmetry` | 两个条件率之差 `P(B|A)-P(A|B)`；缺少任一方向则留空。 |
| `anomaly`, `anomaly_difference` | 官方公开的两个方向共同人数互相冲突时，前者为 `true`，后者为两数差的绝对值；没有两个方向或无冲突时差为 0。这是来源一致性告警，不是统计异常检验。 |

跨部门表中的 `character_*`、`music_*` 分别是两端的规范名、显示名、名次、选择人数和该部门有效选票数；`conditional_denominator` 是来源条件率的分母，`music_overall_rate=music_selection_count/music_ballots` 是音乐总体率；其 `lift=conditional_rate/music_overall_rate`（分母有效时），口径见 `lift_basis`。这类表不具备同一个完整四格选票宇宙，`cosine`/`cosine_ochiai`/`ochiai`/`jaccard`/`pmi`/`pmi_nats`/`npmi`/`phi` 等完整 2×2 列留空。

## 角色评论与投票理由

来源为 `data_processed/character_comments/entity_summary.csv` 的逐实体文本摘要，原文及文本哈希在 `comments.csv.gz`。角色指标表 `vote_explorer/data/analysis_character_metrics_all.csv` 按地区、届次及非空实体 ID 连接；无 ID 命中时只接受唯一名称别名。同名来源、多别名冲突及同一来源重复挂接均为 `ambiguous`，数值留空，不取第一条。来源未正常处理为 `source_error`；找不到来源为 `unmatched`；只有 `ok` 行可用于统计。`ok` 表示成功连接，不保证整届评论全部公开或完整抓取。

| 字段 | 单位、公式与限制 |
|---|---|
| `comments_raw` | 来源保存的原始文本条数，包括空文本。 |
| `comments_nonempty` | 非空文本条数；来源成功而无非空文本可为真实 0。 |
| `comments_unique` | 该地区、届次、角色内的非空文本精确去重条数；不是独立评论者数。 |
| `comment_exact_duplicates` | `comments_nonempty-comments_unique`；重复文本不等于重复投票。 |
| `comment_blank` | `comments_raw-comments_nonempty`。 |
| `comment_avg_chars`, `comment_median_chars` | 非空文本字符数的平均数及中位数，来自上游摘要；无非空文本则空白。字符不是词，长度不是情绪或支持度。 |
| `comment_unique_rate` | `comments_unique/comments_nonempty`，分母为 0 时空白；这是去重后保留的比例，不是删除比例或意见多样性。 |
| `comment_to_selection_ratio` | `comments_nonempty/selection_count`，选择人数缺失或为 0 时空白；不是评论者占投票者比例，不据此推断独立人数。 |
| `comment_data_status` | `ok`、`unmatched`、`ambiguous`、`source_error`；后三者的所有评论数值均为空。 |

`analysis_results/character_comments/role_by_round.csv` 每行一届，覆盖 CN1–11、JP3–22 的 31 个审计范围。`region`/`round`/`round_label` 定位该届，`ranking_entities` 为排行实体行数，`comment_entities_matched` 为 `ok` 行数，`entities_with_nonempty_comments` 为其中非空条数大于 0 的行数；`match_rate=comment_entities_matched/ranking_entities` 是连接成功比例，不是原站抓取完整率。`comments_raw`/`comments_nonempty`/`comments_unique`/`exact_duplicates` 是 **已匹配排行实体内**的计数之和，不能与整个原文归档总数混用；`comments_unique` 不跨角色去重。

`mean_entity_comment_chars=Σ各角色comment_avg_chars/有非空评论的已匹配角色数`，保留每个角色等权的口径，**不是全届评论合并后的平均长度**。schema v2 用此列替代旧 `mean_comment_chars`。`comment_count_selection_pearson` 和 `comment_count_rank_pearson` 在有效的已匹配角色上计算非空评论条数与选择人数/名次的 Pearson 相关；不足两个有效实体或某列为常量则空白。名次越小表示排名越高，需注意方向；这些值没有显著性检验或因果含义。`interpretation` 保存解释限制。

`role_analysis.json` 保存同一逐届结果与定义，`role_analysis.md` 是解释摘要；`unmatched_entities.csv` 列出全部非 `ok` 行，以 `region`/`round`/`round_label`、`entity_id`、`name_cn`/`name_jp`/`canonical_name` 和 `comment_data_status` 定位。其数量及文件哈希见 `analysis_data_manifest.json > character_comments.role_audit`，其中 `unmatched_entities` 是所有非 `ok` 状态合计，明细看 `status_counts`。

## 结构元数据和配对特征

`metadata/character_structure_metadata.csv` 只覆盖 `character_name_crosswalk.csv` 的角色 roster；`metadata/character_structure_metadata_manifest.json` 记录行数与来源。宽表字段及允许证据详见 [结构元数据 schema](../metadata/character_structure_metadata_schema.md)。`character_structure_field_audit.csv` 每个角色每个属性一行：`attribute` 为属性名，`value` 为证据值，`value_status` 区分 crosswalk 原值、参考索引值、人工编码和未验证空白；`basis`/`source`/`version`/`source_sha256` 标明依据，`match_status` 标明匹配结果。THBWiki 参考索引不是官方阵营认证；`stage`/`boss_identity` 当前无已验证值时为空。

`vote_explorer/data/analysis_character_pair_structure_features_all.csv` 是**已观测角色对**与结构信息的连接结果，当前 `analysis_data_manifest.json > character_pair_structure` 记录 82,246 行和上游哈希。列按下表读：

| 字段组 | 含义 |
|---|---|
| `region`, `round`, `round_label`, `pair_category`, `canonical_pair_key`, `pair_key` | 配对所在届次、类别与连接键；每对按无向关系识别。 |
| `name_a/b`, `name_a_cn/b_cn`, `canonical_a/b` | 两端来源名、中文名和规范身份。 |
| `intersection_count`, `data_completeness`, `censoring_status`, `source_type`, `source_path` | 原始已观测同投人数、完整性和来源；不添加未公开的配对。 |
| `metadata_a_status`, `metadata_b_status`, `pair_metadata_status` | 两端和整对的结构元数据匹配/可用状态；不等于统计置信度。 |
| `a_*`, `b_*` | 两端各自的 `crosswalk_first_appearance_work_id`、`reference_first_appearance_work`、`reference_identity_or_title`、`reference_character_type`、`reference_source_group`、`stage`、`boss_identity`、`region`、`region_type`、`community`、`community_type`。前缀只表示端点，值的证据级别见结构审计表。 |
| `same_*` | 在两端属性均已验证时，值相同为 1、不同为 0；任一端未知则空白。包含作品、类型、来源组、关卡、Boss 身份、区域和组织等对应列。`same_first_appearance_work`/`same_character_type`/`same_source_group` 是常用兼容列。 |
| `shared_region`, `common_region`, `shared_community`, `common_community` | 同一区域/组织时保留共同值；空白可能是不同，也可能是证据不足，先看 `same_region`/`same_community`。 |

这里的 `community` 是人工/参考的结构属性；下节的 `community_id` 才是 Louvain 结果，二者完全不同。

## 统计关联输出

四种统计表均在 `analysis_results/network_inference/`，范围由各自运行清单及 `analysis_results/network_coverage.csv` 控制。状态行可以表示不可检验，不能把空 p 或空系数当零。以下给出每一个分析专有列；共同的 `region`/`round`/`metric`/`status`/`warning` 分别是地区届次、被分析指标、计算状态与限制说明。

| 输出 | 字段组与读法 |
|---|---|
| `hypothesis_tests.csv` | `analysis_name`/`hypothesis` 是分析及结构分组；`observation_n`/`control_n` 与两组 `*_median` 为纳入的配对数和中位数；`u_statistic` 为 Mann–Whitney U；`cliffs_delta=P(X>Y)-P(X<Y)`（并列不贡献）；`ci_low/high` 为其 bootstrap 区间；`raw_p` 为节点属性置换双侧 p，`adjusted_p` 为 `adjustment_family` 内的校正 p；`permutations`/`valid_permutations`/`random_seed` 记录计算；`inference_status` 为探索/验证标签，`data_status` 与 `metric_scope` 描述可用性。 |
| `sensitivity_scan.csv` | `threshold_type`/`threshold` 是筛选规则和值；`hypothesis`/`metric`/`node_set`/`data_completeness` 界定场景；`observation_n`/`control_n` 是两组规模；`effect_size` 为 Cliff's delta；`raw_p`/`adjusted_p` 分别为置换和场景族校正值；`eligible_pair_n` 是阈值前有效已观测对数，`effective_pair_n` 是阈值后对数，`pair_coverage=effective/eligible`；`adjustment_method` 可为 Holm/BH/none，`adjustment_family` 记录族；`valid_permutations`/`status`/`warning`/`inference_status` 记录限制。 |
| `sensitivity_summary.csv` | 每个 `region`/`round`/`metric`/`threshold_type`/`hypothesis`/`node_set`/`data_completeness`/`adjustment_method` 的 `tested_thresholds`、`direction_stability`、`significance_stability`、`interpretation`；方向和显著性分别判断，至少两个且各阈值有有效值才谈稳定。 |
| `matrix_correlations.csv` | `matrix_a/b`、`metric_a/b`、`correlation_method` 指明比较对象和 Pearson/Spearman；`node_count` 是共同节点数、`pair_count` 是共同有效上三角配对数；`observed_correlation` 为相关系数，`permutation_p=(极端有效置换数+1)/(有效置换数+1)`；`permutations`/`valid_permutations`/`random_seed` 记录检验；`node_alignment_rule`/`missing_pair_rule` 说明对齐与不补零；`source_complete_a/b` 是两侧来源状态，`complete_pair_matrix` 是**实际比较单元格**完整性；`interpretation_note`/`warning` 标注限制。 |
| `mrqap_coefficients.csv` | `dependent_metric`/`predictor`/`model_type` 是因变量、解释变量和 OLS 或线性概率模型；`coefficient` 是在所列协变量下的回归系数，`ordinary_se`/`ordinary_t`/`ordinary_p` 是普通回归结果，`qap_p` 是节点/Freedman–Lane 置换检验 p；`permutation_scheme`/`permutation_seed`/`permutations`/`permutations_used` 说明运行；`r_squared` 为拟合优度；`n_pairs` 为矩阵候选对数，`complete_case_n` 为所有变量均有效的对数，`n_nodes` 为节点数；`status`/`collinearity_diagnostic` 说明是否可估计。普通 p 不是 QAP p。 |

`analysis_results/network_coverage.csv` 每行一个 `analysis` × `region` × `round`（可含 `comparison_round`）：`status`/`reason` 解释有结果、无来源、仅孤点或不可检验；`observed_pair_rows`、`complete_pair_rows` 是分析输入对数，`matrix_source_pair_rows`、`matrix_source_complete_pair_rows` 是矩阵来源对数；`result_rows` 与 `result_path` 指向输出，`source_scope` 描述纳入政策。此表是跨结果的可用性索引，不替代每个结果的 manifest。

统计量的计算口径：Mann–Whitney `U` 可读作所有观察组/对照组配对中“观察值更大”的次数加并列次数的一半；Cliff's delta 则把“更大”与“更小”的比例相减。Pearson 相关是协方差除以两侧标准差，Spearman 先将数值转换为秩（并列取平均秩）再计算 Pearson。OLS 系数是最小化完整案例残差平方和所得；线性概率模型用相同拟合方式解释显式二值因变量。置换 p 使用 `(同等或更极端的有效置换数+1)/(有效置换数+1)`；bootstrap 区间由重复抽样的效应量分位数构成。检验的节点置换/标签置换方案及重复次数须读该输出的 manifest，不能把 `ordinary_p` 解释为 `qap_p`。

## 社区检测输出

三个目录分别是 `analysis_results/network_communities/`（character）、`.../music/`、`.../cross_department/`。每个 `all_rounds_manifest.json` 列出 31 个逐届 `community_run_manifest.json`；读取时以该清单的路径为准，勿把根目录旧单次输出当作批量结果。每届节点来自该范围的官方/规范实体宇宙，边只来自已观测配对；孤立节点保留。

| 文件 | 字段组与读法 |
|---|---|
| `community_assignments.csv` | `round_label`/`scope`/`node_type`/`canonical_name`/`name_cn`/`name_jp` 定位节点；`community_id`/`community_rank`/`community_size` 是本次 Louvain 分组的标识、排序和人数；`connected_component_id`/`connected_component_size` 是独立连通分量；`weighted_degree` 为相邻边权和，`unweighted_degree` 为边数；`pagerank` 为加权随机游走稳态权重（阻尼 0.85），`betweenness` 为边距 `1/weight` 的归一化最短路径中介性，`k_core` 为忽略权重后的最大 k-core 层数，`bridge_score=跨社区相邻边权和/weighted_degree`（孤点为 0）。 |
| `community_summary.csv` | 每社区 `node_count`/`edge_count`、`internal_weight`（内部边权和）、`total_weighted_degree`（成员加权度和）、`modularity_contribution`（对总 modularity 的贡献），以及 ID/排序。 |
| `modularity_summary.csv` | 全图 `node_count`/`edge_count`、`connected_component_count`/`community_count`、`modularity`（各社区贡献之和）、`degree_assortativity`（边权加权的两端度 Pearson 相关）、`nmi_vs_connected_components`（两种划分的归一化互信息）；`runtime_seconds`/`load_seconds`/`algorithm_seconds`/`peak_memory_bytes`/`benchmark_status` 是运行资源和基准状态，不是网络性质。 |
| `node_centrality.csv` | 同一节点的度、PageRank、betweenness、k-core、bridge score 和两种分组 ID，便于独立读取节点统计。 |

设全图边权和为 `W`、某社区内部边权和为 `W_in`、成员加权度和为 `K`，其 `modularity_contribution=W_in/W-resolution*(K/(2W))^2`（无边图记 0），全图 modularity 为各社区之和。`nmi_vs_connected_components=2*互信息/(两个划分各自的熵之和)`；度同配性是边权加权 Pearson 相关。上述四表的 `algorithm`、`weight_metric`、`threshold`（纳入边的权重下限）、`min_intersection_count`（附加共同人数下限）、`resolution`、`random_seed`、`software_version` 是本次运行参数；`official_faction_source=not_used` 和 `official_faction_note` 明确算法未使用官方阵营。度、桥分数、modularity 等依赖所选图和权重，不能跨不同阈值/节点宇宙直接比较。

`analysis_results/network_inference/unified/` 的四张同名表是上述统计表的统一展示版本，不是新的检验。共同列中，`analysis_id`/`result_id` 是分析与行标识，`feature_id`/`feature_label_zh`/`feature_label_en` 是假设或特征及显示名，`name_*`/`canonical_pair_key` 是可用时的实体标识，`method` 是统计方法，`effect_size`/`effect_size_type` 是效应及单位，`n_pairs`/`n_nodes` 是纳入量，`p_value`/`q_value` 是未校正/校正 p，`adjustment_method`/`adjustment_family` 是校正政策，`missing_policy`/`data_scope`/`source_path`/`source_status`/`warning` 描述限制与来源；`scenario`/`threshold`/`network_scope`/`parameter_delta` 等仅在对应分析场景有值。源表的专有列原样保留，完整列契约见 `metadata/network_inference_output.schema.json` 与统一运行清单。`status=not_estimable` 时效应和 p 留空；`adjustment_method=not_applied` 时 q 留空。
