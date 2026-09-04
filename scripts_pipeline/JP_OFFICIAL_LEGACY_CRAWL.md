# 日本官方旧届数据抓取（第3—16回）

在项目根目录执行（Python 环境需要安装 `lxml`）：

```powershell
python .\scripts_pipeline\crawl_jp_official_legacy.py --rounds 3-16 --workers 8
```

脚本支持断点续跑，默认复用已经保存的汇总页 HTML 和详情 JSON；只有显式传入
`--refresh` 才重新下载。并发数即使传入更大值也会硬性限制为 8。

数据布局：

- `data_raw/jp_official_legacy/round_XX/aggregate`：官方汇总页原始 HTML 与数值表 JSON；
- `.../questionnaire`：官方问卷原始 HTML 与数值表 JSON；
- `.../lists`：角色、音乐、作品（第13回另含搭档）列表原始 HTML；
- `.../details/<category>`：详情页摘要及完整数值表，不含投票评论正文；
- `.../detail_index.csv`：详情源文件索引；
- `.../numeric_table_rows.csv.gz`：逐表逐行的合并数值数据；
- `metadata/jp_official_legacy_manifest.json`：逐 URL 的来源、SHA-256、字节数与落盘位置；
- `metadata/jp_official_legacy_coverage.json`：逐届、逐类别覆盖率；
- `metadata/jp_official_legacy_validation.json`：本地文件完整性校验。

抓取层保留官方网站列出的每一个音乐条目，不在此处合并同曲。后续分析可依据用户已修复的
曲名映射建立 `canonical_track`，把不同作品中的同曲票数叠加后只分析一次，同时保留原条目供复核。
