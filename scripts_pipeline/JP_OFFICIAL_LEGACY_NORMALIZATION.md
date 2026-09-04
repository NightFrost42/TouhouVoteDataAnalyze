# 日本官方旧届数据统一长表（第3—16回）

该步骤完全离线，只读取 `data_raw/jp_official_legacy`，不会重新访问网站：

```powershell
python .\scripts_pipeline\normalize_jp_official_legacy.py
```

输出：

- `data_processed/jp_official_legacy/questionnaire_long.csv`：逐届总体アンケート，逐题、逐项、逐选项长表；
- `entity_questionnaire_long.csv`：第11—16回每个角色／曲目／作品详情中的分组问卷；
- `entity_association_long.csv`：共投、跨部门关联、同票合并曲目的来源版本，以及第13回搭档排名；
- `source_entity_metrics.csv`：主榜名次、点数、一押、由规则精确换算的得票数；
- `normalization_exceptions.csv`：不能安全套用既有结构的表，正常情况下仅作为显式审计清单；
- `metadata/jp_official_legacy_normalization*.json`：输入、程序、输出校验和与语义校验；
- `metadata/jp_official_legacy_component_status.json`：逐届区分“官网未提供”“已抓取”和“抓取失败”。

分母优先采用官网明示值。若页面只给计数和四舍五入比例，程序仅在这些数值共同限定出唯一整数时
写入分母；若有多个候选则保留为空，并写出候选上下界。不会把反推近似值伪装成官网原值。
交叉表按“行分组 × 列选项”拆成长表；即卖会目的表的总体参与分母与参与者条件分母分开记录。
官网自身存在不相容的计数/比例时，原数值照录、分母留空，并在校验元数据中单列为来源警告。
