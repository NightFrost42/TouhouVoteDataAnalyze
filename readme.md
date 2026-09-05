# 东方人气投票数据工作区

## 🌐 网页版入口（推荐）

**[立即打开东方人气投票研究网页版 →](https://nightfrost42.github.io/TouhouVoteDataAnalyze/vote_explorer_web/)**

无需安装桌面工具，直接在浏览器中查看角色、曲子、CP、问卷、同投网络和跨届分析。网页端会按当前筛选读取全量分析数据，并在最后按 Top N 切片展示。

本工作区保存日区第 3–22 回、国区第 1–11 届人气投票的官方原始响应、规范化数值表、覆盖校验和可复算分析。当前完成度以 `metadata/` 中最新的 coverage、validation 与队列状态文件为准；本说明不把“已有文件”误写成“覆盖已经完成”。

## 当前主结构

- `data_raw/`：按站点和届次保存的官方原始响应及站内处理结果。抓取断点依赖这里的文件，不要手工去重或改名。
- `data_processed/`：规范化、统一字段和音乐同曲合并后的分析输入。相同曲目在不同作品中的再收录按既定映射叠加，但只作为一个规范曲目分析。
- `analysis_results/`：由本地程序计算的数值结果，不把截图当作数值来源。
- `scripts_pipeline/`：当前维护的爬虫、规范化、校验、分析程序和爬取控制台。具体控制方式见 `scripts_pipeline/README.md`。
- `metadata/`：manifest、隐藏 journal、覆盖矩阵、校验结果、队列配置/状态和日志。它们同时承担溯源与断点恢复，不能按普通缓存删除。
- `reports/`：覆盖审计、文章核查和清理报告等人类可读文档。
- `tests/`：当前流水线的自动化回归测试。
- `vote_explorer/`：离线查询器、文章分析工作台、便携数据和 Windows 构建脚本；入口与分析口径见 `vote_explorer/README.md`。
- `archive_legacy/`：已退出主流程但仍需追溯的旧程序、旧输出、诊断和环境清单；详见 `archive_legacy/README.md`。

根目录的 xlsx、opju、PNG 以及 `Character-MusicAnalyze.py`、`CharacterAnalyze_jp.py` 是用户数据或手工修订分析，未在本次整理中移动。译名与同曲映射应优先沿用这些已修订数据和当前规范化映射。

## 爬取控制

可双击根目录中的：

- `启动爬取并打开控制台.cmd`：按已保存配置启动/恢复并打开状态面板。
- `打开爬取控制台.cmd`：只打开面板。
- `停止爬取.cmd`：安全停止元数据中精确记录的队列进程。

不要用删除 manifest、journal、run state 或原始响应的方式“重置”失败任务；控制台会从缺失或失败项继续。网站端 5xx/504 也不能通过清本地成功缓存解决。

## 维护与审计

- 本地文件清单：运行 `python .\scripts_pipeline\inventory_workspace.py` 生成；清单含本机状态，不纳入仓库
- 统一覆盖：`metadata/unified_component_coverage.json` 与 `.csv`
- 归档清单：`archive_legacy/archive_manifest.csv`
- 本次整理：`reports/workspace_cleanup_2026-08-19.md`
- 中日投票—社媒—梗/二创纵向主报告：`reports/jp_cn_community_poll_longitudinal.md`
- 地区化社群旁证与角色覆盖：`analysis_results/community_poll_alignment/`；源事件、评论/弹幕和Pixiv快照见 `metadata/community_*.csv`、`metadata/pixiv_tag_snapshots.csv`
- 公开社交讨论与官方附加数据三角核对：`reports/social_discussion_notes.md`、`analysis_results/social_triangulation/`
- 可重复整理脚本：`scripts_pipeline/organize_workspace.ps1`（默认只预演，显式传入 `-Execute` 才执行）

清理缓存时只删除可再生成的 `__pycache__`、`.pyc` 等；不要把 `data_raw/`、`metadata/*manifest*`、隐藏 journal、coverage、validation、队列状态或日志当作缓存。

## 当前发布数据

`datasets/votes_cn1-9_jp3-22/` 是当前统一投票数据集（CN1–11、JP3–22）；旧的 `votes_cn1-9_jp3-21/` 快照已移入 `archive_legacy/`，不再参与构建。投票分析工具使用 `vote_explorer/data/` 中的分析表，并附带 CN/JP 独立的同人曲投票窗口、CP/组合、同投和问卷关联数据。

构建产生的 `build/`、`dist/`、本地 PyInstaller 依赖、压缩包、`*.spec` 和 Python 缓存已加入根目录 `.gitignore`；发布目录仍可在本机保留，但不作为源代码提交。目录版和单文件版的具体命令、数据同步方式与启动检查见 `vote_explorer/README.md` 的“构建可发送的 Windows 版本”。
