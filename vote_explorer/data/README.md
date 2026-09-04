# CN1–11 / JP3–22 投票结果数据集

本目录是从工作区已有的本地爬取资料离线整理出的可直接读取数据集。普通名次表范围为中国区 CN1–11 与日区 JP3–22。CN1–9 使用旧版排行页/工作簿，CN10–11 使用完整现代 GraphQL base.json；CSV 使用 UTF-8 with BOM，便于 Excel、pandas 和 R 直接打开。

## 文件

- `rankings.csv`：统一长表，每行一个地区、届次、榜单类别和实体。
- `ballot_totals.csv`：源页面明确发布的各届各类别有效票数；无法可靠取得的字段留空。
- `analysis_cp_metrics_all.csv`：CN2–11 已发布的官方 CP/组合排行。
- `analysis_vote_combinations_all.csv`：跨届组合比较表；官方 CP 缺失时使用同投人数替代，并在 `data_source` 标记。
- `analysis_music_metrics_all.csv`：曲子投票指标与三种同人曲数量口径；CN2–11 和 JP3–22 使用各自投票窗口，CN1/JP3 的届间口径为空。
- `analysis_character_music_links_all.csv`：角色—原曲打标关系及对应的投票/同人曲指标，用于角色×音乐交叉。
- `analysis_character_music_covote_all.csv`：官方公开的角色—曲子条件同投记录；未公开的届次不补 0。
- `analysis_questionnaire_all.csv`：总体问卷比例；题目和选项按地区/届次保留来源差异。
- `analysis_entity_questionnaire_all.csv.gz`：逐实体问卷交叉；CN2–4 为详情页群体统计，CN5–11 为条件问卷结果，JP17–22 为日区公开数据。
- `cn_alignment_audit.csv`：CN1–9 投票榜中未能唯一对齐详情实体的行（保留原名和原因）；CN10–11 现代榜使用名称键并在 `alignment_status` 标明。
- `cn_legacy_advanced_rankings.csv.gz`：CN5–9 官方问卷条件榜与实体条件榜，已带稳定实体键。
- `cn_legacy_advanced_questionnaire.csv`：上述高级结果中的问卷答案条件子集。
- `cn_legacy_advanced_pairs.csv.gz`：CN5–9 官方问卷两两交叉（pair）单元格。
- `cn_advanced_rankings.csv.gz`：统一 CN5–11 高级搜索原子条件榜；CN10/11 还保留现代站的 CP 聚合结果。
- `cn_advanced_questionnaire.csv`：统一 CN5–11 问卷答案原子条件榜（仅分类 Single/Multiple；Input/open text 保留元数据但不作为数值答案）。
- `cn_advanced_pairs.csv.gz`：CN5–11 统一问卷两两交叉单元格；CN10/11 没有旧版批量端点，数据来自逐格归档的官方 Boolean 查询。
- `cn_legacy_detail_demographics.csv.gz`：CN2–4 详情页公开的逐实体投票群体统计（性别、年龄、接触时间等）；这是早期静态详情口径，不冒充后期高级搜索 API。
- `cn_entity_inventory.csv`：CN1–9 每个已抓取详情项的稳定键、显示名别名、普通榜行数、高级条件行数、早期群体统计行数和 item API 文件清单；可用它逐项核对抓取与投票结果。CN10–11 的现代榜没有旧版详情索引，直接追溯 `graphql/base.json`。
- `manifest.json`：输入/输出 SHA-256、行数、覆盖范围和校验结果。

## 大文件分卷

`cn_advanced_questionnaire.csv`、`cn_legacy_advanced_questionnaire.csv` 和
`analysis_covote_pairs_all.csv` 已按完整记录切为约 80 MB 一卷。每卷都保留表头，
分卷清单为同名 `.parts.json`，包含原文件大小和 SHA-256。查询器启动时会自动按
编号读取并合并，不需要手工改名或拼接。

## 字段约定

`points` / `weighted_score` 保留源站的加权分或积分；`vote_count` 是该实体的总选择人数：CN 使用源站总票数，JP 在官方同时公开积分和所需顺位数时按当届 2/1 或 3/2/1 计分规则精确还原。无法唯一还原的 JP 榜单仍留空，不会估算或写成 0。`first_choice_count` 是 CN 本命数或 JP 一押数。`vote_share` 是实体总选择人数除以该届该类别有效投票人数。百分比字段统一转换为 0–1 比例。`rank_prev`、`rank_prev2` 是源站公布的上两届名次。缺失值为空字符串。

CN 规则、可投票数量和加权方式在历届有变化；JP 旧版与现代版也不是同一计分制度。因此不要把不同地区/届次的 `points` 或 `weighted_score` 当成可直接横向比较的统一分数。并列名次会保留源站名次，使用 `(region, round, category, rank, entity_name)` 作为稳定行键。

## 纳入的榜单类别

当前输出类别：character, cp, music, overall, partner, spell, spell_system, spell_user_overall, work。CN 的作品/组合榜来自可恢复的官方排行页，CN10–11 的角色、曲子、CP榜来自完整现代 GraphQL；JP3 的 spell、spell_system、spell_user_overall、overall 等榜单按不同类别保留，避免与角色榜混淆。CN1 没有逐实体投票群体详情；CN2–4 的详情页包含逐实体群体统计，另存为 `cn_legacy_detail_demographics.csv.gz`；CN5–9 的后期高级条件榜、实体条件榜和官方两两交叉表另存为 `cn_legacy_advanced_*`；CN10/11 的现代 GraphQL 原子条件和逐格问卷交叉数据合并进 `cn_advanced_*`。

## 覆盖概览

共 33,533 行排行、94 行票数汇总。详细分组行数见 `manifest.json` 的 `row_counts_by_region_round_category`。

## 生成与空值

本目录由 `scripts_pipeline/build_vote_explorer_analysis_data.py` 生成，属于应用随附数据，不应手工编辑。缺失值统一留空而不是写成 0：例如首届没有“上一届结束—本届结束”的同人曲增量，或某地区/届次没有官方问卷题目时，工作台会在注释中说明原因。问卷关联工作台另有“最少实体投票人数”阈值，按 `selection_count` 过滤低票角色/曲子，默认不筛选。

## 来源与复现

构建脚本为 `scripts_pipeline/build_vote_dataset.py`，只读取本地 `data_raw/`、`data_processed/` 和现有规范化工作簿，不联网。每条排行记录都保留 `source_type` 与 `source_path`，可沿路径回溯到原始 HTML 表、HTML 内嵌数组、现代 JSON 或现有工作簿；`entity_key` 是可跨表连接的稳定键，`alignment_status` 明确区分已匹配、歧义、未提供详情和待人工复核。
