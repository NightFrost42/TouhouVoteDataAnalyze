# 网络矩阵结构相关分析

运行脚本：

```powershell
python .\scripts_pipeline\analyze_matrix_correlations.py
```

默认使用 200 次固定种子 `20260929` 的同步节点标签置换，并写入：

- `matrix_correlations.csv`
- `matrix_correlations_run_manifest.json`（与同目录 MRQAP 的 `model_run_manifest.json` 分开）

两者位于本目录。可用 `--permutations`、`--random-seed`、`--current-round ROUND --compare-round ROUND` 和多个
`--round-pair CURRENT:COMPARE` 调整运行；`--no-cross-round` 只输出同届比较。

## 比较范围

- `analysis_covote_pairs_all.csv`：角色×角色和曲子×曲子同投矩阵，比较 `raw_count`、`lift`、`cosine`。
- `analysis_vote_combinations_all.csv`：只使用 `data_source=official_cp` 且没有第三个成员的官方二人 CP 项目，作为稀疏 `vote_count` 矩阵；同投 fallback、三人组合和未公布项目不加入 CP 矩阵。
- 默认同届比较同类型矩阵之间的 `raw_count/lift/cosine`，以及角色同投 raw count 与官方 CP vote count；跨届比较覆盖固定范围内所有可用的相邻届。未观测到的前一届矩阵不会被当作空矩阵。
- 角色×曲子是二部关系，不与角色×角色或曲子×曲子直接相关。若未来需要比较，必须先明确可审计的二部矩阵投影，而不能因为两表都有“关系”字段就强行对齐。

## 统计口径

1. 节点使用 canonical ID 的交集，节点输入顺序不影响结果。
2. 对称矩阵只取严格上三角；对角线和自环不参与计算。
3. 只使用两张矩阵共同实际观测的配对。空白、NA、NaN 和未列出的配对保持缺失，绝不自动写成 0；真实观测的 0 会保留。
4. `pair_count` 是该行真正参与相关的配对数量。`complete_pair_matrix=true` 只有在两边都声明完整矩阵且共同节点的全部 `n*(n-1)/2` 配对都存在时才成立；来源完整但某个指标本身未定义的单元格仍会使该指标比较不完整。
5. `metric_a`/`metric_b` 同时输出 Pearson 和 Spearman。Spearman 对并列值使用平均秩；样本不足或某一指标为常量时相关为空。
6. `permutation_p` 是把一张矩阵的节点标签同步置换（行和列使用同一个置换）后得到的双侧有限置换 p 值，计算为 `(极端置换数+1)/(有效置换数+1)`。它不是普通向量相关的渐近 p 值。
7. **矩阵结构相关，不代表因果。** 相关高只表示两种关系在当前节点、届次和缺失规则下的结构相似，不能证明一张关系导致另一张关系。

CSV 保留用户要求的字段，并附带 `complete_pair_matrix`、`valid_permutations`、两侧来源完整性和 `warning`，方便审计实际覆盖。运行清单记录输入分卷、输出哈希、随机种子、置换数和缺失配对政策。
