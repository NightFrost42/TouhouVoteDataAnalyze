# 东方人气投票研究｜GitHub Pages 网页版

这是与 `vote_explorer/` 桌面 Tk 工具隔离的静态网页。网页只读取仓库中的完整分析 CSV，以及由桌面版 `AnalysisRepository` 预先生成的 `web_data/templates.json`（用于没有必要重复扫描大表的模板），不导入或修改桌面工具的 Python 代码。基础排行、同人曲交叉、CP、普通问卷、实体问卷和同投项目均保留全量数据；最低票数、Top N、搜索和名次范围在浏览器端过滤，不会在构建时把低票记录删掉。

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
- `analysis_covote_pairs_all.csv.part-001`
- `analysis_covote_pairs_all.csv.part-002`
- `analysis_covote_pairs_all.csv.parts.json`（同投分卷校验信息；音乐内部同投聚类按需读取两个分卷）

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

未改为动态查询的桌面模板继续使用构建脚本中的标准参数（例如默认名次区间和比较届次）；网页端仍支持届次、Top N、名称搜索、名次范围、最低数据值、变化方向、阵营、实体问卷题目/选项和 CSV 下载。实体问卷和同投模板会在选中时按需读取全量 CSV；同投分卷约 145 MB，手机首次打开同投项目可能需要等待下载和解析，但不会把完整数据预先截断。音乐内部同投聚类仍在选中模板时才读取两个完整分卷，因此最低共同人数设为 0 时也能看到低于默认阈值的公开关系。

Top N 不改变原始投票数据或统计分母。共投角色网络是一个有意的例外：Top N 先选取名次范围内的前 N 个角色（阵营筛选后再取），图表和结果表从这批角色中使用同一组最多 N 条关系；没有入选关系的角色仍保留为节点，名称以少量高连接角色标注，其余可悬停查看。
