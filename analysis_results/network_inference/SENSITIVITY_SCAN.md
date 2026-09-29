# 网络阈值敏感性分析

运行 `python scripts_pipeline/network_sensitivity_scan.py`，默认配置见
`metadata/network_sensitivity_scan.json`。脚本输出同目录下的
`sensitivity_scan.csv`、`sensitivity_summary.csv` 和 `sensitivity_report.md`。
也可使用 `--config`、`--output`、`--covote`、`--features`、`--cp` 指定文件。

配置中的 `scans` 可扫描 `intersection_count`、`lift` 和 `cp_vote_count`；
`node_sets` 支持 `all_observed`、带 `rank_max` 的 `top_ranked`，以及带
`ids` 列表的 `explicit`。`data_completeness` 支持 `complete_matrix`、
`observed_only` 和 `partial_observed_pairs`。`metrics` 可指定任意已发布的
数值列；cosine、φ 等完整矩阵指标只在完整行上检验。JP 前列的 rate-ratio
lift 不会被误当作完整矩阵的 independence lift。CP 阈值只覆盖官方公布的
二人组合，未公布组合始终为未知，不视作 0 或未形成。

CSV 的 `effect_size` 是 Cliff's delta；`raw_p` 来自固定种子的节点属性置换。
`adjustment_method` 可为 `holm`、`bh` 或 `none`。校正族由每个区域、届次、
节点集、完整性条件和单个阈值场景内的所有指标与假设构成；主检验文件
`hypothesis_tests.csv` 不参与校正。不同阈值复用同一数据，绝非独立验证。
`pair_coverage` 是通过分类且指标有效的配对数，除以施加当前阈值前具有
有效指标的已观测配对数；对应计数分别在 `effective_pair_n` 和
`eligible_pair_n`。观察组及对照组规模各自列出。

`warning` 中的 `low_power_heuristic` 表示任一组小于配置的 `min_group_n`。
这是样本量警告，不是正式功效计算。摘要分别给出方向稳定性与校正后
显著性稳定性；只有至少两个阈值且每个阈值都有可用值时才判为稳定或混合。
