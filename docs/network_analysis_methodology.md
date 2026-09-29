# 同投网络：方法与解释边界

本页解释研究结果能说明什么。逐列含义见 [数据字典](network_analysis_data_dictionary.md)，逐次运行和核验见 [复现指南](network_analysis_reproducibility.md)。地区与届次的可用性以 `vote_explorer/data/analysis_data_manifest.json` 的 `covote_coverage` 和 `analysis_results/network_coverage.csv` 为准；不能仅凭目录里有文件判断有可用关系。

## 先区分四种关系

同投边表示同一选票同时选择了两个角色或两首曲子；跨部门边表示同一选票同时选择了角色和曲子。它们是投票行为的描述，**不是 CP 投票、原作关系或因果证据**。`analysis_vote_combinations_all.csv` 的 `data_source=official_cp` 才是已公开的官方 CP/组合项目；`data_source` 标为同投替代时，不能称作官方 CP。`analysis_character_factions.csv` 是另行整理的原作群体映射；Louvain 社区只是网络结构分组，**不是官方阵营**。

可作三层陈述：

1. **探索性描述**：某届已观测配对的人数、条件率、网络形状或社区分组。阈值扫描属于这一层；多个阈值使用重复数据，不是独立验证。
2. **统计关联**：在明确的配对宇宙、缺失规则、检验方法和校正族下，报告效应量、区间及 p 值。显著不等于效应大，未显著不证明没有关系；不同指标可能给出不同方向。
3. **因果解释**：本数据没有随机分配或足以排除混杂的设计。即使同投、结构特征和原作分组相关，也不能推断一项导致另一项。

## 来源和完整性

| 范围 | 同部门角色/音乐配对 | 可说与不可说 |
|---|---|---|
| CN10–11 | 官网完整四格矩阵，逐届逐类经过配对数、边际与对称校验 | 明确记录的 `intersection_count=0` 是观测零；可计算完整 2×2 指标。 |
| JP11–22 | 官网公开的关联前列，列表以外右删失 | 可描述已公开配对及其已公布方向；**未公开配对不等于零**，不能补齐四格或宣称全网排名。 |
| CN1–9、JP3–10 | 无同部门官方同投配对来源 | 排名表不能倒推两两共同人数；没有配对行不等于 0。 |

跨部门角色—曲子表的官方来源覆盖 CN10–11 高级条件结果及 JP17–22 角色详情，且有自己的 `data_completeness`、`censoring_status` 和选票分母；角色票与音乐票可能处于不同投票宇宙。其条件率和相对于总体率的 `lift` 须按该表字段读，不能套用同部门完整四格、φ 或独立性基准。每次使用前检查该行状态与来源。`lift` 是观察比例与参考比例之比，**不是稳定性或置信度**；小分母和筛选后的前列尤其会放大它。

完整四格约定为 `m00` 两者都选、`m01` 仅 B、`m10` 仅 A、`m11` 都不选。只有 `metric_status=exact_complete_2x2` 的行具备完整四格指标。JP 的 `lift_basis=published_conditional_overall_rate_ratio` 是官网条件率除以总体率的口径，不应与 CN 的 `independence_2x2` 混成同一估计量。方向冲突行保留 `conflicting_published_directions` 状态，不能擅自选取一个方向。逐项公式和空值规则见数据字典。

## 结构特征与网络统计

结构元数据的角色范围由 `metadata/character_name_crosswalk.csv` 定义，参考索引不是官方认证。`stage` 与 `boss_identity` 当前没有已审核的 roster 级来源时保持空白；空白不是“不同关卡”或“不是 Boss”。`same_*` 在任一端属性未知时也未知，不写成 0。来源级别、人工编码依据和逐字段状态见 `metadata/character_structure_metadata_schema.md` 与审计表。原作结构字段与投票同投是两种不同来源，不可互相补值。

`hypothesis_tests.csv` 用已观测角色配对按结构特征分组，给出 Mann–Whitney U、Cliff's delta、bootstrap 区间和节点属性置换 p；默认假设标为 `exploratory`，Holm 校正在清单所列族内进行。阈值 `sensitivity_scan.csv` 用相同数据改变边阈值、节点集及完整性条件，另设校正族；方向稳定与显著性稳定分别报告。`matrix_correlations.csv` 在共同节点的**共同已观测配对**上比较矩阵，用同步节点标签置换估计双侧 p；两个来源各自完整并不保证用于比较的有效矩阵完整。`mrqap_coefficients.csv` 只接受显式完整的无向角色矩阵，普通回归 `ordinary_p` 与置换 `qap_p` 不能互换；`no_complete_cases`、`metric_unavailable` 等状态不是零效应。有关每种输出的实际覆盖、低功效和警告，应同时读对应 manifest。

社区结果对 character、music、cross_department 三个范围分别运行加权 Louvain。当前三个 `all_rounds_manifest.json` 各列 CN1–11、JP3–22 共 31 届，参数为 `intersection_count` 权重、阈值 100、分辨率 1、固定种子；每届独立运行。无同投来源届次仍保留榜单节点，可能产生 `computed_isolates_only`，**不能把这解释成已发现独立社群**。`connected_component_id` 是连通分量，`community_id` 是算法分区，两者不等同。社区 ID 只在对应范围、届次和参数内有意义；不能跨地区/届次直接对号，也不能用来补结构元数据或原作阵营。

## 阅读结果的顺序

先看地区、届次、`scope`/`pair_category`、来源和 `data_completeness`；再看节点/配对计数、零与未知的区分；然后看指标公式、阈值和校正族；最后读效应量、p、状态及警告。不同地区与届次的投票规则、选票数量、公开程度和实体宇宙不一致，部分范围**不能直接横向比较**。更强的结论需要另行定义可比人群、统一分母并处理选择偏差与混杂。
