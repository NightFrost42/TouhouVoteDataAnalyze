# 网络分析结果范围与复现

本页把每种输出连到其数据来源和运行证据。字段释义见 [数据字典](network_analysis_data_dictionary.md)，可作出的结论见 [方法说明](network_analysis_methodology.md)。路径相对仓库根目录。**现有结果的参数以对应 run manifest 为准**，不要拿后来修改的配置文件反推；例如当前 `metadata/network_hypothesis_tests.json` 与已保存的 `hypothesis_tests_manifest.json` 中置换次数并不相同。

## 输出、来源和范围

| 输出 | 来源与实际范围 | 权威覆盖/运行证据 |
|---|---|---|
| `vote_explorer/data/analysis_covote_pairs_all.csv` | CN10–11 角色/音乐完整四格；JP11–22 角色/音乐官网关联前列。CN1–9、JP3–10 无同部门配对来源。 | `vote_explorer/data/analysis_data_manifest.json > covote_coverage` 给出逐届、类别的状态、来源路径、期望/观测配对、显式零和校验；大表读取 `.parts.json` 当前列出的卷。 |
| `vote_explorer/data/analysis_character_music_covote_all.csv` | 角色—音乐二部同投；CN10–11 官方高级条件结果、JP17–22 官方角色详情页，其余届次无此来源。仅按该表实际行和状态使用，不借用同部门完整性。 | `analysis_data_manifest.json > availability.character_music_covote`、`outputs` 的行数/哈希及表内 `source`、`data_completeness`、`censoring_status`。 |
| `metadata/character_structure_metadata.csv`、`...field_audit.csv` | 当前 crosswalk roster 的结构属性；参考索引和人工条目逐字段分开。 | `metadata/character_structure_metadata_manifest.json` 与 `metadata/character_structure_metadata_schema.md`。 |
| `vote_explorer/data/analysis_character_pair_structure_features_all.csv` | 已观测角色对连接结构特征；当前 manifest 记录 82,246 行。 | `analysis_data_manifest.json > character_pair_structure` 记录上游元数据 SHA-256、输出路径及未知政策。 |
| `analysis_results/network_inference/hypothesis_tests.csv` | 角色已观测配对的结构分组；`intersection_count`/公布方向条件率可用性随来源，`share`/Jaccard 需完整矩阵。结果行可为不可检验。 | `hypothesis_tests_manifest.json` 记录配置副本、纳入/排除、实际种子与置换、输入/输出哈希。 |
| `analysis_results/network_inference/sensitivity_scan.csv`、`sensitivity_summary.csv`、`sensitivity_report.md` | 配对阈值、节点集和完整性场景的探索性扫描；不并入主假设检验校正族。 | 这些文件当前没有独立 run manifest，参数与输入哈希不能从 `metadata/network_sensitivity_scan.json` 反证已保存输出；见 `SENSITIVITY_SCAN.md` 和表内场景列。 |
| `analysis_results/network_inference/matrix_correlations.csv` | 同届指标矩阵与官方二人 CP 矩阵比较，以及清单指定的相邻届；只用共同已观测配对。无源届次不视为空矩阵。 | `matrix_correlations_run_manifest.json` 给出实际比较届次、输入/输出哈希、置换参数及纳入规则；`analysis_results/network_inference/README.md` 给出统计口径。 |
| `analysis_results/network_inference/mrqap_coefficients.csv` | 仅 CN10–11 显式完整的角色矩阵可进入候选；JP 前列被排除。当前默认模型含未验证的 `stage`，相关模型行可能为 `no_complete_cases`，不能报告为有效系数。 | `model_run_manifest.json > mrqap.groups/excluded_groups` 逐组列状态；另记录输入哈希、模型、seed 和置换方案。 |
| `analysis_results/network_communities/{by_round,music/by_round,cross_department/by_round}/<届次>/` | character、music、cross_department 三个独立范围，每个批量清单各有 CN1–11、JP3–22 共 31 次运行。无官方同投来源的届次可只有孤点。 | 各范围 `all_rounds_manifest.json` 是逐届路径目录；每个 `community_run_manifest.json` 记录输入/输出哈希、节点、边、阈值、算法和缺失政策。 |
| `analysis_results/network_coverage.csv`、`.json` | 角色网络相关分析逐届/比较届的可用性索引；用于识别 `unavailable_*`、`computed_isolates_only` 等，而不是替代原表或三范围社区清单。 | 表内 `status`、`reason`、配对计数和 `result_path`。 |
| `analysis_results/network_inference/unified/` 与 `vote_explorer_web/web_data/research/` | 前者是统计表的统一适配结果，后者是网页按分片发布的已有离线结果；不新增原始观测。 | 前者的 `model_run_manifest.json`、`metadata/network_inference_output.schema.json`；后者的研究索引与构建时输入清单校验。网页打包不重新做统计。 |

社区批量清单当前三范围均为 `algorithm=louvain`、`weight_metric=intersection_count`、`threshold=100`、`resolution=1`、`random_seed=20260801`、`data_policy=observed`。按逐届 manifest 的 `included_pairs`，character/music 的有边届次为 CN10–11、JP11–22，cross_department 为 CN10–11、JP17–22；其余运行是无官方同投边的节点结果。**31 次运行不表示 31 届都有完整配对矩阵**。单次运行根目录中的 CSV 可能与批量清单不属于同一届；研究网页按批量清单读取。

## 用结果前的固定检查

评论接入的来源摘要、处理总数及逐届输出哈希见 `analysis_data_manifest.json > character_comments`；原始处理总数不等于已连接排行实体的汇总数。评论派生列的单独刷新命令为 `python scripts_pipeline/build_vote_explorer_analysis_data.py --comments-only`，会更新角色表的评论列、31 届评论审计及对应清单，不重建同投矩阵。列定义见[评论数据字典](network_analysis_data_dictionary.md#角色评论与投票理由)。`covote_metrics_audit.status` 读取报告内的实际结果：报告失败为 `FAIL`、缺失为 `UNAVAILABLE`、格式/状态无效为 `INVALID`；文件存在不等于审计通过，旧报告的 PASS 也不证明新输入已重新审计。

1. 在 `analysis_data_manifest.json > covote_coverage[届次][类别]` 查 `status`、`source_path`、`expected_pairs`、`observed_pairs` 和 `metric_status_counts`。`not_available` 不生成配对，`official_published_leading_list` 的列表外为未知；只有 `complete_matrix` 且具体行 `metric_status=exact_complete_2x2` 才读四格指标。
2. 在 `analysis_results/network_coverage.csv` 看分析状态，再打开对应运行清单。核对 `inputs`/`outputs` 的路径、SHA-256、计数、实际参数及 `pair_inclusion`；对无独立清单的阈值扫描，明确标注“运行参数未由 manifest 证实”。
3. 对社区结果，先看 `all_rounds_manifest.json > run_manifests`，再读目标届次的五件套和 manifest。若 `included_pairs=0` 或覆盖表为 `computed_isolates_only`，只报告保留节点，不报告已发现的同投社群。
4. 报告结果时同时写地区、届次、类别/范围、来源完整性、节点/有效配对数、指标、阈值、校正方法、效应量、状态和警告。跨届/地区先确认规则、分母和实体宇宙可比；不同来源的 lift 不直接比较。

可用以下命令核验支持统一 schema 的运行清单所记录文件哈希（在仓库根目录执行）：

```powershell
python scripts_pipeline/model_run_manifest.py verify analysis_results/network_inference/hypothesis_tests_manifest.json --root .
python scripts_pipeline/model_run_manifest.py verify analysis_results/network_inference/matrix_correlations_run_manifest.json --root .
python scripts_pipeline/model_run_manifest.py verify analysis_results/network_inference/model_run_manifest.json --root .
python scripts_pipeline/model_run_manifest.py verify analysis_results/network_communities/by_round/CN11/community_run_manifest.json --root .
```

复算前检查当前数据与清单哈希是否匹配；工作区原表、映射或配置变化会产生新版本，不应覆盖旧清单后仍引用旧结论。研究型网页只打包已存在结果：`python vote_explorer_web/build_static_bundle.py --research-only`；这个步骤不验证原始配对矩阵，也不运行统计模型。
