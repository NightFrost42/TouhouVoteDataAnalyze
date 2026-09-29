# 东方人气投票研究｜GitHub Pages 网页版

「网络统计与结构社区」的离线结果请配合仓库级[方法说明](../docs/network_analysis_methodology.md)、[逐列数据字典](../docs/network_analysis_data_dictionary.md)及[覆盖与复现](../docs/network_analysis_reproducibility.md)阅读。网页只发布已有结果；显著性、lift 和社区标签均有各自的解释边界。

## 离线研究型网络

「分析项目 → 网络统计与结构社区」读取构建阶段打包的统计结果，和桌面版完整分析中的普通同投网络分开。新增层级包括结构假设检验、矩阵相关、MRQAP / QAP 系数、探索性阈值敏感性、社区汇总、社区成员、节点中心性、网络整体统计和数据覆盖。角色、音乐、跨部门的社区按各自运行清单覆盖 CN1–11、JP3–22；没有结果的届次显示不可用，不从排行推造配对或补零。

先按需要运行仓库已有的离线统计脚本，再打包网页：

```powershell
python vote_explorer_web/build_static_bundle.py --research-only
```

不带 `--research-only` 时先打包研究结果，再按原流程构建桌面模板。研究打包只读取已经生成的结果和运行清单，不运行统计检验或读取原始矩阵。参数仍在离线脚本/配置中修改；网页阈值、方法和社区算法只选择已完成场景。

### 来源与完整性

- 读取 `analysis_results/network_inference/` 当前三个估计器结果及各自运行清单，不使用可能较旧的 `unified/` 汇总。构建校验清单列出的结果 CSV 的 SHA-256；缺失或不匹配直接失败，保留已发布索引。不会宣称重新验证了原始输入矩阵。
- 社区按三个范围的 `all_rounds_manifest.json` 引用读取，避免混入旧的单届根目录产物。无批量清单时支持单次运行清单。结构社区不是原作阵营。
- 阈值扫描和覆盖表没有运行清单时标记 `no_run_manifest`；未报告的随机种子、请求置换次数等保持未知，不能从当前配置反推。
- 表格和图下注释显示完整性、删失、探索性、配对数口径和运行参数；可展开清单查看参数、输入记录、哈希及完整性警告。`not_reported` 表示未知，不能理解为没有删失。
- 完整矩阵筛选只接受明确证据。矩阵相关以有效 `complete_pair_matrix` 判断，两个来源各自完整不证明有效矩阵完整；MRQAP 的完整案例数与来源配对总数分开。无法估计的系数和 p 留空，普通回归 p 不冒充 QAP p。
- 探索性结果默认隐藏，可显式开启。阈值扫描不混入主检验校正。最低配对数在假设检验中指两组之和，在 MRQAP 中指完整案例，在节点统计中指度，在社区汇总中指内部边，在整体统计中指网络边，表格逐行说明。

### 部署与下载

发布 `index.html`、`app.js`、`research.js`、`styles.css` 和 `web_data/research/`。研究路径相对网页定位，不受普通视图 `?data=` 影响。首页不会请求研究索引、桌面大快照或原始矩阵；选择研究入口才读取索引与当前“层级 × 届次/比较 × 范围”分片，最多缓存三个研究分片。重复参数以共享列值压缩，保留原始字符串、空白及长整数种子。

“下载当前结果 CSV”导出展示行；“下载全部筛选结果 CSV”包含同一分片筛选后的全部行，不受 Top N 限制。CSV 保留所有原始列和 `web_` 来源/筛选字段，不舍入统计量。旧网络、矩阵、气泡、变化、阵营筛选和普通下载保持原入口；只有主动选择旧的全量同投模板时才读取原始分卷（当前 manifest 约 302 MB），研究视图始终不读取。

分片以内容哈希命名，索引最后写入。重建保留旧分片以兼容部署期间的旧缓存索引；干净发布目录可仅复制当前索引引用的文件。

固定断言检查：

```powershell
python -m unittest discover -s tests -p test_vote_explorer_web_research.py
node --test tests/test_vote_explorer_web_research.mjs
```

安装 Playwright 的环境还可运行 `node tests/test_vote_explorer_web_research_browser.cjs`；`BROWSER_CHANNEL=msedge` 可使用本机 Edge。浏览器固定断言覆盖手机加载范围、统计筛选、缺失状态、两种 CSV 导出、恢复默认和旧图表；旧矩阵/网络/气泡/变化使用小型固定测试源，不必下载完整原始矩阵。

这是与 `vote_explorer/` 桌面 Tk 工具隔离的静态网页。网页只读取仓库中的完整分析 CSV，以及由桌面版 `AnalysisRepository` 预先生成的 `web_data/templates.json`（用于没有必要重复扫描大表的模板），不导入或修改桌面工具的 Python 代码。基础排行、同人曲交叉、CP、普通问卷、实体问卷和同投项目均保留各自来源范围；最低票数、Top N、搜索和名次范围在浏览器端过滤，不会在构建时把低票记录删掉。同投 CSV 中 CN10/11 是角色/音乐完整四格矩阵，JP11–22 是官方公开关联前列；列表外配对未知，不补 0。

## 本地预览

在仓库根目录执行：

```powershell
pwsh.exe -NoLogo -NoProfile -Command "C:\Python314\python.exe -m http.server 8000"
```

浏览器打开 `http://localhost:8000/vote_explorer_web/`。不能直接双击 `index.html`，因为浏览器会阻止 `file://` 读取 CSV。

## GitHub Pages

如果 Pages 发布整个仓库（根目录或 `main` 分支），直接把 `vote_explorer_web/` 作为入口即可。默认数据路径是 `../vote_explorer/data/`，适合当前仓库布局。

如果只发布网页目录，请把下列文件复制到网页目录下的 `data/`，并在 URL 后追加 `?data=./data/`：

- `analysis_character_metrics_all.csv`
- `analysis_music_metrics_all.csv`
- `analysis_cp_metrics_all.csv`
- `analysis_questionnaire_all.csv`
- `analysis_vote_combinations_all.csv`
- `analysis_entity_questionnaire_all.csv.gz`（选择桌面版实体问卷模板时按需读取并由浏览器解压）
- `analysis_character_music_covote_all.csv`（跨部门同投集中聚类按需读取）
- `analysis_covote_pairs_all.csv.parts.json`（同投分卷校验与实际分卷名；网页按 manifest 动态读取，支持任意卷数）

同时投指标列统一包含 raw count、双向 conditional rate、lift、cosine/Ochiai、Jaccard、PMI/NPMI 和 φ。只有 `metric_status=exact_complete_2x2` 的 CN 行提供完整四格派生指标；JP 的 `lift` 是官网 conditional/overall rate ratio，JP 前列的 cosine/Jaccard/PMI/φ 等字段为空，不会从未发布配对补出四格。网页读取 `analysis_covote_pairs_all.csv.parts.json` 动态发现分卷，不假设固定卷数。


同时保留 `web_data/templates.json`。它包含桌面版全部 72 个模板、CN1–11/JP3–22 的静态结果、结果表和说明；普通问卷对比、实体问卷关联模板及角色同投矩阵、网络、气泡、同投指标、跨届变化、方向、累计、四象限、异常和自定义同投会在浏览器中从完整 CSV 重算，因此可以切换中文区/日文区各自真实的题目和选项，不需要在手机浏览器中运行 Python。

数据更新后，在仓库根目录执行：

```powershell
pwsh.exe -NoLogo -NoProfile -Command "C:\Python314\python.exe vote_explorer_web/build_static_bundle.py"
```

## 已覆盖功能

- CN1–11、JP3–22 角色/曲子排行；指标包括名次、分数、实际选择人数、选择率等。
- 曲子投票 × 同人曲数量散点图：届间新增、截至投票结束累计、抓取时点累计总数。
- CP 官方投票排行，并保留来源字段。
- 地区/届次独立的问卷选项比例图；中文区和日文区不会把同名选项误合并。
- 问卷关联的“最少实体投票人数”过滤，默认 0；正数时排除低票或缺失实体投票人数的角色/曲子。
- 当前结果表 CSV 下载。
- 图表标题栏提供 75%–300% 手动缩放；放大后保留 SVG 原始比例并在图表区域滚动查看，不会为了适应屏幕把复杂图表整体压缩。手机窄屏会将缩放按钮移到标题下方，电脑端则与下载按钮并列。

- 桌面版完整模板目录：折线、条形、分组/堆叠柱、散点、气泡、哑铃、热力图和网络图；单届结果与跨届/对比结果在同一个“桌面版完整分析”入口中按项目层级分组，避免两个入口重复。
- 图表支持鼠标悬浮、键盘聚焦和手机点击提示；气泡图会直接标出组合名称，并同时保留人数、集中倍数和 φ 等详细信息。

网页入口按桌面项目结构在同一个完整入口中分为两层：单届结果（角色/曲子排行、同人曲交叉、CP、问卷，以及桌面单届模板）位于“分析项目根目录”；跨届趋势、两届哑铃、变化和组合对比等模板集中位于“对比分析项目（统一对比表）”。这样不会因为重复入口造成同一模板出现两次，也不会删减桌面版功能。

未改为动态查询的桌面模板继续使用构建脚本中的标准参数（例如默认名次区间和比较届次）；网页端仍支持届次、Top N、名称搜索、名次范围、最低数据值、变化方向、阵营、实体问卷题目/选项和 CSV 下载。实体问卷和同投模板会在选中时按需读取全量 CSV；原始同投分卷按当前 manifest 读取（目前约 302 MB），手机主动打开这些全量同投项目可能需要等待下载和解析，但不会把完整数据预先截断。音乐内部同投聚类在选中模板时才读取 manifest 列出的全部分卷，因此最低共同人数设为 0 时也能看到低于默认阈值的公开关系。研究型网络只加载离线结果分片。

Top N 不改变原始投票数据或统计分母。共投角色网络是一个有意的例外：Top N 先选取名次范围内的前 N 个角色（阵营筛选后再取），图表和结果表从这批角色中使用同一组最多 N 条关系；没有入选关系的角色仍保留为节点，名称以少量高连接角色标注，其余可悬停查看。
