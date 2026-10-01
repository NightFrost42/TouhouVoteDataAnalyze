# CN1–11 / JP3–22 投票结果数据集

同投原表、结构特征、统计检验与社区输出的逐列说明见[网络分析数据字典](../../docs/network_analysis_data_dictionary.md)；来源范围及运行清单见[复现指南](../../docs/network_analysis_reproducibility.md)，结论边界见[方法说明](../../docs/network_analysis_methodology.md)。榜单覆盖 CN1–11 / JP3–22 不代表所有届次都有同投来源。

本目录是从工作区已有的本地爬取资料离线整理出的可直接读取数据集。普通名次表范围为中国区 CN1–11 与日区 JP3–22；CN1–9 使用旧版排行页/工作簿，CN10–11 使用完整现代 GraphQL base.json。CSV 使用 UTF-8 with BOM，便于 Excel、pandas 和 R 直接打开。

## 文件

- `rankings.csv`：统一长表，每行一个地区、届次、榜单类别和实体。
- `ballot_totals.csv`：源页面明确发布的各届各类别有效票数；无法可靠取得的字段留空。
- `cn_alignment_audit.csv`：CN1–9 投票榜中未能唯一对齐详情实体的行（保留原名和原因）；CN10–11 现代榜使用名称键并在普通表的 `alignment_status` 标明。
- `cn_legacy_advanced_rankings.csv.gz`：CN5–9 官方问卷条件榜与实体条件榜，带稳定实体键。
- `cn_legacy_advanced_questionnaire.csv`：CN5–9 高级结果中的问卷答案条件子集。
- `cn_legacy_advanced_pairs.csv.gz`：CN5–9 官方问卷两两交叉（pair）单元格。
- `cn_legacy_detail_demographics.csv.gz`：CN2–4 详情页逐实体投票群体统计；字段含性别、年龄、接触时间等实际公开题目及实体内/全体比例。
- `manifest.json`：输入/输出 SHA-256、行数、覆盖范围和校验结果。
- `analysis_character_metrics_all.csv`：角色分析长表，覆盖 CN1–11 与 JP3–22；未公开字段留空。
- [角色评论逐届审计](../../analysis_results/character_comments/role_by_round.csv)：位于仓库的 `analysis_results/`，不是本数据目录下的文件；评论指标已并入 `analysis_character_metrics_all.csv`。
- `analysis_music_metrics_all.csv`：曲子分析长表，覆盖 CN1–11 与 JP3–22；支持名次、分数、选择人数、第一顺位率等。
- `analysis_music_catalog_unmatched.csv`：按届次列出未能安全对应到根目录 `TouhouMusicInfo.xlsx` 的曲名；这些行会保留原始名称，不会被模糊猜测合并。
- `analysis_covote_pairs_all.csv`：同投关系长表。CN10/11 覆盖角色×角色、曲子×曲子的完整四格矩阵；JP11–22 覆盖官网实际公开的两类关联前列，未公开配对不补 0。
- `analysis_cp_metrics_all.csv`：官方 CP/组合榜，包含 CN2–11 已发布的项目。
- `analysis_vote_combinations_all.csv`：组合跨届比较表；官方 CP 缺失时以同投人数替代，并由 `data_source` 标明。
- `analysis_questionnaire_all.csv`：总体问卷长表，覆盖 CN1–11 静态/现代汇总与 JP17–22（题目按届次实际公开情况提供）。
- `analysis_work_catalog.csv`：作品共享目录，包含中文/日文名、作品发布时间顺序代码和排序键；作品问卷图按此目录排序，不按人气名次。
- `analysis_entity_questionnaire_all.csv.gz`：逐角色、曲子、作品的问卷长表，覆盖 CN2–4 详情群体统计、CN5–11 官方问卷条件以及 JP17–22；含 `entity_key` 和 `source_kind`，可按届次、类别和稳定实体键连接投票结果。
- `analysis_cn_advanced_pairs_all.csv.gz`：供分析工作台读取的 CN5–11 官方问卷交叉单元格。
- `analysis_character_music_links_all.csv`：由 `data_processed/music_canonical/local_music_merged.csv` 的 `mapped_characters_json` 生成的角色—曲子打标关系，覆盖 CN1–11、JP3–22；包含双方名次、选择人数和选择率，可直接用于交叉分析。
- `analysis_character_factions.csv`：角色与原作群体的可审计交叉表。前四项为红魔馆、地灵殿、秘封俱乐部、神灵庙，之后是其他原作群体和“作品首登：……”分析 cohort；角色可同时属于多个群体，并保留 THBWiki 页面 URL 与映射依据。
- `analysis_data_manifest.json`：附加分析表的覆盖范围、行数、校验值及缺失原因。

## 大文件分卷

`cn_advanced_questionnaire.csv`、`cn_legacy_advanced_questionnaire.csv` 和
`analysis_covote_pairs_all.csv` 已按完整记录切为约 80 MB 一卷。每卷都保留表头，
同名 `.parts.json` 保存原文件大小、SHA-256 和分卷顺序。查询器会自动读取并合并
分卷；如需恢复完整文件，可运行 `scripts_pipeline/split_large_files.py --all --merge`。

## 字段约定

`points` / `weighted_score` 保留源站的加权分或积分；`vote_count` 是该实体的总选择人数：CN 使用源站总票数，JP 在官方同时公开积分和所需顺位数时按当届 2/1 或 3/2/1 计分规则精确还原。无法唯一还原的 JP 榜单仍留空，不会估算或写成 0。`first_choice_count` 是 CN 本命数或 JP 一押数，`vote_share` 是实体总选择人数除以该届该类别有效投票人数。百分比字段统一转换为 0–1 比例。`rank_prev`、`rank_prev2` 是源站公布的上两届名次。`analysis_work_catalog.csv` 的 `release_date` / `release_order` 仅表示作品首次公开时间及跨类别排序键，不是投票名次；`release_code` 保留 `game060`、`music050`、`novel015` 等来源代码。缺失值为空字符串。

`analysis_covote_pairs_all.csv` 另有 `pair_category`、`data_completeness`、`censoring_status` 和 `complete_pair_matrix` 来源字段：CN10/11 为角色/音乐完整四格矩阵（`complete_matrix`、`not_censored`、`True`），JP11–22 为官网公开关联前列（`official_published_leading_list`、`right_censored_by_official_list`、`False`）。只有 CN 完整矩阵中明确出现的 `intersection_count=0` 才是真实观测 0；JP 列表外配对以及 CN1–9、JP3–10 无来源配对都保持不存在，不生成 0 行；逐届逐类别状态见 `analysis_data_manifest.json` 的 `covote_coverage`。

同投字段统一按 A/B/总体四格定义：`raw_count`/`intersection_count` 为共同选择人数，`conditional_rate_a_to_b` 和 `conditional_rate_b_to_a` 为两个方向的条件率，`lift` 在 CN 完整矩阵中为相对于独立基准的倍数；`cosine`/`ochiai`、`jaccard`、`pmi`/`npmi` 和 `phi` 仅在 `metric_status=exact_complete_2x2` 时填充。JP 前列只保留已发布 raw count、conditional rate 与 `lift_basis=published_conditional_overall_rate_ratio`；完整 2×2 字段留空，不能以未发布配对补出 `m01`/`m10`/`m11`。

CN 规则、可投票数量和加权方式在历届有变化；JP 旧版与现代版也不是同一计分制度。因此不要把不同地区/届次的 `points` 或 `weighted_score` 当成可直接横向比较的统一分数。并列名次会保留源站名次，使用 `(region, round, category, rank, entity_name)` 作为稳定行键。

## 纳入的榜单类别

当前输出类别：character, cp, music, overall, partner, spell, spell_system, spell_user_overall, work。CN 的作品/组合榜来自可恢复的官方排行页，CN10–11 的角色、曲子、CP 榜来自完整现代 GraphQL；JP3 的 spell、spell_system、spell_user_overall、overall 等榜单按不同类别保留，避免与角色榜混淆。CN1 没有逐实体群体详情；CN2–4 的详情页群体统计写入 `cn_legacy_detail_demographics.csv.gz` 并合并到 `analysis_entity_questionnaire_all.csv.gz`；CN5–11 的后期问卷答案条件、实体条件和官方两两交叉表另存为 `cn_legacy_advanced_*` / `cn_advanced_*`。manifest 会分别记录详情统计与条件 API 的覆盖，不把两种来源混为一谈。

## 覆盖概览

共 33,533 行排行、94 行票数汇总。详细分组行数见 `manifest.json` 的 `row_counts_by_region_round_category`。

附加分析表的实际行数和校验值以 `analysis_data_manifest.json` 为准；其中总体问卷同时包含 CN1–11 静态/现代汇总和 JP17–22，逐实体问卷包含 CN2–4 详情统计、CN5–11 高级条件结果及 JP17–22。曲子指标已对 CN1–11、JP3–22 统一应用 `TouhouMusicInfo.xlsx` 的全名/译名和所属角色主题变体规则，并在同一届将同一规范曲目合并为一行；未能安全对应的曲名见 `analysis_music_catalog_unmatched.csv`。同投表保留 CN10/11 原始角色/音乐矩阵的完整实体宇宙，不因曲目 canonical 合并而删掉矩阵顶点；JP11–22 只保留官方角色/音乐关联前列，列表外配对未知。CN1–9、JP3–10 没有同部门官方同投来源，不会伪造 0。JP3–16 的排行、分数和可推导选择人数可用，但第二顺位、实体问卷及部分人口指标没有公开时保持空值。分析工作台遇到这类部分公开指标时，会保留能计算的系列；例如旧届顺位结构显示“第一顺位/非第一顺位”，不会将缺失的第二顺位写成 0。

角色评论/投票理由按 CN1–11、JP3–22 的实际公开范围保存。`comments_nonempty`、`comments_unique`、`comment_avg_chars` 等字段只描述文本数量、重复和长度；`comment_to_selection_ratio` 是文本条数与选择人数的比值，不能解释为“有多少投票者评论”，因为来源没有评论者与投票者的一一对应关系。无法匹配、同名歧义或来源错误的排行实体保持空值（分别为 `unmatched`、`ambiguous`、`source_error`），逐届匹配率和未匹配清单见 `analysis_results/character_comments/role_by_round.csv` 与 `unmatched_entities.csv`。评论正文仍只在独立压缩归档中保存，展示时必须按纯文本处理。

评论字段公式、状态和逐届汇总口径见[评论数据字典](../../docs/network_analysis_data_dictionary.md#角色评论与投票理由)。`mean_entity_comment_chars` 为各角色平均长度的等权均值，替代含义不清的旧列 `mean_comment_chars`。

## 来源与复现

构建脚本为 `scripts_pipeline/build_vote_dataset.py`，只读取本地 `data_raw/`、`data_processed/` 和现有规范化工作簿，不联网。每条排行记录都保留 `source_type` 与 `source_path`；`entity_key` 可连接投票榜、详情和高级搜索，`alignment_status` 区分已匹配、歧义、未提供详情和待人工复核。
