# 日文官方第3—22回统一数值层

本目录只合并官方旧站与现站的字段口径，不翻译实体名，不跨届合计，也不把官网只公布的关联前列扩充成完整矩阵。生成脚本为 `scripts_pipeline/build_jp_unified.py`，输入与输出哈希见 `metadata/jp_unified_report.json`。

## 文件

- `aggregate_questionnaire_long.csv.gz`：总体アンケート，第3—22回，6,774行。
- `entity_questionnaire_long.csv.gz`：逐实体アンケート，第11—22回，353,188行；第3—10回官网未发布同构数值详情。
- `entity_association_long.csv.gz`：逐实体关联前列，第11—22回，296,796行；现代站同一关联按多种排序重复发布的行已折叠，并保留 `published_orderings` 与 `published_positions`。

## 数值口径

- 所有可用于比例分析的 `rate` / `conditional_rate` / `overall_rate` 均为0—1比例。
- 旧站0—100百分数在此层除以100，原始HTML/JSON与来源哈希不变。
- 分母无法由官网精确恢复时保持空值，不用四舍五入百分比反推。
- `lift = conditional_rate / overall_rate`；任一分母或比例缺失时保持空值。
- 现代官网有2条稀疏实体明细直接发布 `rate=2.0`。统一层不截断、不猜测：官方值保存在 `official_conditional_rate_raw`，分析比例、差值与lift留空，`rate_status=official_rate_outside_proportion_domain`。具体行见统一报告。

## 名称与关联范围

- `source_name`、`target_name`、题目与选项均保留日文官网原文。
- 本层不做同曲合并；同曲再收录叠加在 `data_processed/music_canonical/` 单独完成，原始来源行仍保留。
- `entity_association_long.csv.gz` 是官网发布范围内的前列关联，不代表所有实体两两组合；不得把缺少的组合当作零。

## 复现

```powershell
python scripts_pipeline/build_jp_unified.py
```

脚本包含届次覆盖、比例范围、来源映射等强校验；任一校验失败时不会生成“通过”的报告。

本目录仍是当前分析流水线的输入，不属于历史归档：`vote_explorer` 的同投替代组合、社区对齐和部分关系分析会直接读取其中的实体问卷/关联表。CN1–11 数据不写入本层，统一国区数据见 `datasets/votes_cn1-9_jp3-22/`。
