# 工作区整理报告（2026-08-19）

## 结果

本次将退出主流程的旧分析链整体归档，删除可再生成缓存和无效/重复探针，同时保留全部正式原始数据、规范化数据、数值分析、工作簿与抓取断点。

- 本次新归档 1,285 个文件，共 140,220,587 字节（133.72 MiB）。
- 归档总清单现有 1,291 个文件，共 140,599,364 字节；逐文件存在性、大小与 SHA-256 校验全部通过。
- 实际释放 508,818,216 字节（485.25 MiB）。其中损坏 `.venv` 为 500,316,466 字节，可再生成缓存共 1,511,964 字节，重复/无效探针为 6,989,786 字节。
- 根目录 131 个 `.tmp_cn_*` 已全部处理：110 个正式层同哈希副本删除，14 个错误页删除，2 个无分析数据/语义重复探针删除，5 个小型网络诊断归档。
- 唯一缺失的有效第 5 届 CP 探针先提升到正式原始层并写入 manifest/journal，随后才删除临时副本。

完整机器可读记录见 `metadata/workspace_cleanup_report.json`、`metadata/cn_probe_cleanup.csv` 与 `archive_legacy/archive_manifest.csv`。

## 归档范围

- 旧 Wiki 标签与文本分析链（含其专用缓存、字体、停用词和输出）
- 已知字段缺陷且缺少当前补充问卷的旧单体 JSON 分析链
- 被当前数值流水线取代的旧绘图/早期规范化链
- 过期工作区清单、清理计划、旧停机报告和网络探针诊断

这些文件按功能成组移动，避免留下看似可运行但缺少输入或输出的半套程序。归档不是删除；原路径、目标路径和哈希均可在归档清单中追溯。

## 删除范围

- 指向失效解释器和旧磁盘路径的 `.venv` 已删除；仅保留不含本机路径的 49 项包版本清单 `archive_legacy/environment_py311_broken/packages.csv`。
- 项目 `__pycache__`、`.pyc` 和已退出 Runner 的可再生成 stdout/stderr 空日志。
- 与正式层 SHA-256 完全一致的临时探针副本、明确的 5xx/错误页及不含分析数据的探针。

## 明确保留

- `data_raw/`、`data_processed/`、`analysis_results/`
- 所有 manifest 及隐藏 journal、coverage、validation、normalization、队列配置/状态/run state 和当前阶段日志
- 全部 xlsx、opju、两张人气统计 PNG
- 用户修订的 `Character-MusicAnalyze.py` 与 `CharacterAnalyze_jp.py`
- 三个一键控制 cmd、当前控制台、Runner、爬虫和测试

主 manifest 与隐藏 journal 没有合并：两者承担不同的恢复语义，journal 还可能保存比压缩后主清单更晚的失败记录。

## 校验

- 清理执行前后 Python 回归均为 124 项通过。
- 控制台 `app.js`、`eta.js` 通过 Node 语法检查。
- `organize_workspace.ps1` 通过 PowerShell 解析检查。
- 国区旧站离线校验在清理快照时确认 3,882 个成功正式文件均存在且哈希正确；覆盖本身仍未完成，不能把完整性通过解释为所有届次已经抓完。
- 清理结束时根目录无 `.tmp_cn_*`，全项目无 `.venv`；归档中的 5 个 `.tmp_cn_*` 是刻意保留的诊断证据。

爬取运行状态属于独立的实时状态，继续以控制台和 `metadata/data_crawl_queue_state.json` 为准，本报告不覆盖后续启动、停止或网站端 504。
