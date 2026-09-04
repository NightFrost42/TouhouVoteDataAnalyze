# JP3—22 / CN1—11 逐届逐组件覆盖矩阵

生成时间：`2026-09-02T14:14:01Z`。本表由 `scripts_pipeline/build_unified_coverage.py` 离线生成，只读取 `metadata/` 与 `data_processed/`。

状态：`A` = available_crawled，`O` = official_not_offered，`F` = fetch_failed，`N` = not_applicable，`P` = pending。部分抓取一律记 `P`；抓取失败不会降格成 `O`。

| 平台/届 | 主榜 | 问卷定义 | 问卷结果 | 问卷趋势 | 实体问卷明细 | 关联/共投 | 条件榜 | 开放文本 |
|---|---|---|---|---|---|---|---|---|
| JP3 | A | A | A | N | O | O | N | P |
| JP4 | A | A | A | N | O | O | N | P |
| JP5 | A | A | A | N | O | O | N | A |
| JP6 | A | A | A | N | O | O | N | A |
| JP7 | A | A | A | N | O | O | N | A |
| JP8 | A | A | A | N | O | O | N | A |
| JP9 | A | A | A | N | O | O | N | A |
| JP10 | A | A | A | N | O | O | N | A |
| JP11 | A | A | A | N | A | A | N | P |
| JP12 | A | A | A | N | A | A | N | P |
| JP13 | A | A | A | N | A | A | N | P |
| JP14 | A | A | A | N | A | A | N | P |
| JP15 | A | A | A | N | A | A | N | P |
| JP16 | A | A | A | N | A | A | N | P |
| JP17 | A | A | A | N | A | A | N | P |
| JP18 | A | A | A | N | A | A | N | P |
| JP19 | A | A | A | N | A | A | N | A |
| JP20 | A | A | A | N | A | A | N | A |
| JP21 | A | A | A | N | A | A | N | A |
| JP22 | A | A | A | N | A | A | N | A |
| CN1 | A | A | A | O | O | O | N | P |
| CN2 | A | A | A | O | O | O | N | P |
| CN3 | A | A | A | O | O | O | N | P |
| CN4 | A | A | A | O | O | O | N | P |
| CN5 | A | A | A | A | A | O | N | P |
| CN6 | A | A | A | A | A | O | N | P |
| CN7 | A | A | A | A | A | O | N | P |
| CN8 | A | A | A | A | A | A | N | P |
| CN9 | A | A | A | A | A | A | N | P |
| CN10 | A | A | A | A | A | A | A | A |
| CN11 | A | A | A | A | A | A | A | A |

## 状态统计

| 状态 | 行数 |
|---|---:|
| `available_crawled` | 149 |
| `official_not_offered` | 31 |
| `fetch_failed` | 0 |
| `not_applicable` | 49 |
| `pending` | 19 |

## 校验与注意事项

- 矩阵应有 30 届 × 8 组件 = 240 行；实际 248 行，唯一键 248 个，校验 `PASS`。
- 当前优先范围（JP3—22 + CN1—11）完成判定 `PASS`；CN10—11 若快照尚未齐全仍保留为 `pending`，不会伪装成已完成。
- 明确抓取失败共 0 行；它们均保留为 `fetch_failed`。
- 尚待抓取、规范化或完整性认证共 19 行；它们均保留为 `pending`。
- `official_not_offered` 只来自现有 metadata 的明确状态；`not_applicable` 仅表示统一组件在该平台/接口代际没有同构含义。
- JP17—21 的逐实体详情均已在 processed 长表中出现；即使旧 manifest 的 detail_rounds 滞后，也以本次稳定表快照记录实际覆盖。
- CN10 的条件榜与共投若未达到 expected 数量，即使已有部分本地行也记 `pending`。
- CN10—11 的实体问卷明细由现代站 `queryQuestionnaire(query=...)` 专用断点阶段补抓；快照未齐时保持 `pending`，不会把接口存在误报成 `not_applicable`。

## 产物校验和

- `metadata/unified_component_coverage.csv`: `8d88f65ddc81f6355ac1ea526b7c73fbd9793f949fc681add795d8cb74fc9211`
- `metadata/unified_component_coverage.json`: `a63ff37b4d8522f5f49d573d9fd290667ff0f7ff9b762d2f93a487a63aba3763`

逐行证据、观察行数、预期数量和备注见 CSV/JSON。
