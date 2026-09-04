# CN1–11 / JP3–22 投票结果数据集

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
- `analysis_music_metrics_all.csv`：曲子分析长表，覆盖 CN1–11 与 JP3–22；支持名次、分数、选择人数、第一顺位率等。
- `analysis_music_catalog_unmatched.csv`：按届次列出未能安全对应到根目录 `TouhouMusicInfo.xlsx` 的曲名；这些行会保留原始名称，不会被模糊猜测合并。
- `analysis_covote_pairs_all.csv`：同投关系长表，覆盖本地已公开且属于数据范围的 JP11–22 以及 CN10/11 完整现代角色矩阵。
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

CN 规则、可投票数量和加权方式在历届有变化；JP 旧版与现代版也不是同一计分制度。因此不要把不同地区/届次的 `points` 或 `weighted_score` 当成可直接横向比较的统一分数。并列名次会保留源站名次，使用 `(region, round, category, rank, entity_name)` 作为稳定行键。

## 纳入的榜单类别

当前输出类别：character, cp, music, overall, partner, spell, spell_system, spell_user_overall, work。CN 的作品/组合榜来自可恢复的官方排行页，CN10–11 的角色、曲子、CP 榜来自完整现代 GraphQL；JP3 的 spell、spell_system、spell_user_overall、overall 等榜单按不同类别保留，避免与角色榜混淆。CN1 没有逐实体群体详情；CN2–4 的详情页群体统计写入 `cn_legacy_detail_demographics.csv.gz` 并合并到 `analysis_entity_questionnaire_all.csv.gz`；CN5–11 的后期问卷答案条件、实体条件和官方两两交叉表另存为 `cn_legacy_advanced_*` / `cn_advanced_*`。manifest 会分别记录详情统计与条件 API 的覆盖，不把两种来源混为一谈。

## 覆盖概览

共 33,533 行排行、94 行票数汇总。详细分组行数见 `manifest.json` 的 `row_counts_by_region_round_category`。

附加分析表的实际行数和校验值以 `analysis_data_manifest.json` 为准；其中总体问卷同时包含 CN1–11 静态/现代汇总和 JP17–22，逐实体问卷包含 CN2–4 详情统计、CN5–11 高级条件结果及 JP17–22。曲子指标已对 CN1–11、JP3–22 统一应用 `TouhouMusicInfo.xlsx` 的全名/译名和所属角色主题变体规则，并在同一届将同一规范曲目合并为一行；未能安全对应的曲名见 `analysis_music_catalog_unmatched.csv`。CN10/11 的角色同投矩阵来自现代官方数据；其他届次没有官方同投矩阵的地方不会伪造 0。JP3–16 的排行、分数和可推导选择人数可用，但第二顺位、实体问卷及部分人口指标没有公开时保持空值。分析工作台遇到这类部分公开指标时，会保留能计算的系列；例如旧届顺位结构显示“第一顺位/非第一顺位”，不会将缺失的第二顺位写成 0。

## 来源与复现

构建脚本为 `scripts_pipeline/build_vote_dataset.py`，只读取本地 `data_raw/`、`data_processed/` 和现有规范化工作簿，不联网。每条排行记录都保留 `source_type` 与 `source_path`；`entity_key` 可连接投票榜、详情和高级搜索，`alignment_status` 区分已匹配、歧义、未提供详情和待人工复核。
