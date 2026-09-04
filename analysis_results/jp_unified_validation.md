# JP unified 独立验证

结论：**PASS**。本报告未调用生成器，直接重读源表、压缩长表和 provenance report。

## 核心结果

- 三张输出实测行数：aggregate 6,774；entity questionnaire 353,188；entity association 296,796。均与构建报告及源表守恒关系一致。
- 届次：aggregate 完整覆盖 JP3—22；实体问卷和实体关联覆盖 JP11—22（JP3—10 的两张实体表没有源行，不是补零）。
- 现代关联：原始 233,976 行，按官方实体对唯一化后 178,050 行，折叠 55,926 行；重复组的非排序字段差异 0，ordering/position 还原差异 0，数值差异 0。
- 两条官方 rate=2 异常均保留 raw、count、denominator 和原始 delta；`conditional_rate`、分析用 `delta_points`、`lift` 均留空。异常行 2/2 通过。
- 所有分析用 rate 字段均在 [0,1] 或为空；违规数 aggregate=0、entity questionnaire=0、association=0。
- 现代关联只覆盖相应候选宇宙的 3.93%（178,050/4,528,605），且行级类型为 `published_leading_conditional_co_vote`，因此不能解释为完整矩阵。

## 行数守恒

| 输出 | legacy 源行 | modern 源行/唯一行 | 输出行 | 守恒 |
|---|---:|---:|---:|:---:|
| aggregate_questionnaire | 5,040 | 1,734 | 6,774 | 是 |
| entity_questionnaire | 125,706 | 227,482 | 353,188 | 是 |
| entity_association | 118,746 | 178,050 | 296,796 | 是 |

## 每届行数

| JP届次 | aggregate | entity questionnaire | entity association |
|---:|---:|---:|---:|
| 3 | 102 | 0 | 0 |
| 4 | 161 | 0 | 0 |
| 5 | 154 | 0 | 0 |
| 6 | 183 | 0 | 0 |
| 7 | 227 | 0 | 0 |
| 8 | 261 | 0 | 0 |
| 9 | 529 | 0 | 0 |
| 10 | 216 | 0 | 0 |
| 11 | 617 | 10,240 | 2,849 |
| 12 | 614 | 13,209 | 15,915 |
| 13 | 665 | 13,644 | 20,608 |
| 14 | 270 | 28,652 | 26,214 |
| 15 | 514 | 28,956 | 26,417 |
| 16 | 527 | 31,005 | 26,743 |
| 17 | 236 | 33,080 | 28,359 |
| 18 | 248 | 34,393 | 29,043 |
| 19 | 272 | 39,745 | 29,489 |
| 20 | 319 | 40,035 | 29,806 |
| 21 | 350 | 40,665 | 30,345 |
| 22 | 309 | 39,564 | 31,008 |

## 审计提示

- 无。

机器可读的逐项检查见 `analysis_results/jp_unified_validation.json`。
