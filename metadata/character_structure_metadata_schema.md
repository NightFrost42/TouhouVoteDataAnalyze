# 角色结构元数据（schema v1）

## 目的与边界

`character_structure_metadata.csv` 是当前项目角色规范表的结构元数据宽表；它不是投票、人气、标签或社区检测结果。roster 只来自 `metadata/character_name_crosswalk.csv`，因此不会因为分析数据出现新字符串而自动扩张。

- 主键是 `(canonical_name, crosswalk_key)`。
- `canonical_name` 是现有分析使用的规范化当前中文角色名；`canonical_name_cn` 保留 crosswalk 的显示名。
- `crosswalk_key` 是 crosswalk 中原样保存的 `character_jp_normalized`。不要用昵称、搜索命中、模糊相似度或社群图结果替换它。
- 所有 CSV 使用 UTF-8 with BOM；缺失值统一为空字符串。

## 字段

| 字段 | 含义 | 允许的证据/限制 |
|---|---|---|
| `canonical_name`, `canonical_name_cn`, `crosswalk_key`, `character_jp` | 当前规范角色与 crosswalk 身份键 | 直接来自 crosswalk；不重命名、不拆分组合标签 |
| `crosswalk_first_appearance_work_id` | crosswalk 中原始的“首次出现作品”编码 | 只复制原值；不能根据数字猜测作品标题。对应审计行的 basis/source/version 会记录原始文件与哈希 |
| `reference_first_appearance_work` | 保存的 THBWiki 参考索引的作品表述 | 仅作 reference-index 值，不代表官方认证；只接受确定性原文匹配 |
| `reference_identity_or_title` | 参考索引中的身份/称号原文 | 不转换成区域、社群或 Boss 身份 |
| `reference_character_type`, `reference_source_group` | 参考索引的原始分类字段 | 保留原值，不把 `source_group` 当作世界观区域或组织 |
| `stage` | 关卡编号/关卡位置 | 当前没有通过审核的 roster 级来源，故 v1 全为空；不得从社区搜索标题或梗反推 |
| `boss_identity` | Boss / 中 Boss / EX Boss 等身份 | 当前没有通过审核的 roster 级来源，故 v1 全为空；不得从投票或社区内容补齐 |
| `region`, `region_type` | 世界观区域及其类型 | 只接收人工台账中的显式条目；v1 的值是 editorial manual mapping，不等于由图或投票检测出的事实 |
| `community`, `community_type` | 正式组织/社群及其类型 | 只接收人工台账中的显式条目；`formal_organization` 与 `species_group` 不混写 |
| `reference_match_status` | 参考索引匹配方式 | `exact_character_key_thb`、`exact_canonical_cn_fun`、`exact_character_jp`、`normalized_character_jp` 或 `unmatched`；歧义不选任意一行 |
| `crosswalk_table_path`, `crosswalk_source_path`, `crosswalk_source_sheet` | crosswalk 表及其上游工作簿定位 | 仅描述来源，不表示上游字段已经被官方复核 |
| `reference_source_path`, `reference_source_url`, `reference_snapshot_date`, `reference_list_standard` | 参考索引的文件、页面、快照日期和声明 | 参考索引明确标注为 `thbwiki_not_official_opinion` 时，不得省略该限制 |
| `metadata_status` | 该行有 crosswalk、reference、人工台账中的哪些来源 | 仅表示来源覆盖，不是置信度或官方等级 |

## 逐字段审计

`character_structure_field_audit.csv` 对每个角色和以下每个属性保留一行：

`crosswalk_first_appearance_work_id`、`reference_first_appearance_work`、`reference_identity_or_title`、`reference_character_type`、`reference_source_group`、`stage`、`boss_identity`、`region`、`region_type`、`community`、`community_type`。

- `value_status=crosswalk_source_value`：原样复制当前 crosswalk。
- `value_status=reference_index_value`：原样复制已匹配的保存参考索引，不能写成“官方”。
- `value_status=manual_coded_value`：来自 `character_structure_manual_overrides.csv`；`basis`、`source`、`version` 必须同时非空。
- `value_status=unverified_blank`：没有被允许的证据；`value`、`basis`、`source`、`version` 和 `source_sha256` 都保持空白。

人工台账的每一行都要给出：

```text
canonical_name_cn,attribute,value,value_type,basis,source,version
```

台账中的角色名必须精确命中当前 crosswalk。任何未来的 stage/Boss 编码也必须先进入台账并附带明确来源，不能直接编辑生成宽表。

## v1 事实覆盖

manifest (`character_structure_metadata_manifest.json`) 是计数和 SHA-256 的权威记录。v1 当前覆盖为：

- crosswalk roster：217 行，主键唯一；
- crosswalk 原始作品编码：151 行；空白 66 行；
- 保存参考索引确定匹配：165 行；未匹配 52 行；
- 区域人工映射：33 行；社群人工映射：47 行；
- 关卡：0 行；Boss 身份：0 行。二者明确留空，不用社区搜索结果、社区标签、投票或网络检测结果补齐。

## 禁止来源

结构字段不得由以下来源推断或补齐：`analysis_results/community_poll_alignment/`、`analysis_character_factions.csv`、Bilibili/Tieba/Pixiv 快照、`character_community_tag_coverage.csv`、图/网络聚类或任何 community-detection 输出。输入哈希、禁止片段和构建结果写在 manifest 中。

重建命令：

```bash
python scripts_pipeline/build_character_structure_metadata.py
```
