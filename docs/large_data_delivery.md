# 大数据分卷、网页懒加载与发布检查

网页不再读取全届同投 CSV 或完整实体问卷。所有分片都在离线阶段生成，不裁剪原始行、不补零、不在网页首次加载时运行统计检验。

## GitHub 发布约束

本仓库不使用 Git LFS。超过 GitHub 单文件限制的逻辑文件必须提交 manifest 和普通 Git 分卷，且每个分卷保持小于 100 MiB；原始整文件只在本地重建并由 `.gitignore` 排除。克隆后无需下载额外对象：查询器会直接按 manifest 读取同投分卷；需要评论原文整文件时，在仓库根目录执行下面的恢复命令，脚本会逐卷校验 SHA-256 后再原子写入原路径。

```powershell
python scripts_pipeline/split_binary_archive.py restore data_processed/character_comments/comments.csv.gz.binary-parts.json
```

提交前可检查索引中的所有候选文件，确保没有文件触及 GitHub 的 100 MiB 限制：

```powershell
git add -A
python scripts_pipeline/check_git_file_limits.py
```

## 构建

从仓库根目录运行：

```powershell
python vote_explorer_web/build_static_bundle.py
python scripts_pipeline/audit_web_shards.py
python vote_explorer_web/build_pages.py
```

发布 `dist/pages` 的内容，入口为 `vote_explorer_web/`。不要直接把整个源码仓库上传到 Pages。发布目录只复制当前 manifest 引用的分片，排除评论原文、离线源表、历史分片、桌面安装包和构建备份，并检查总大小小于 1 GiB、单文件小于 100 MiB。

`web_data/templates.json` 现在是模板目录与可用性索引；82 个模板各有独立内容分片。`web_data/tables/index.json` 按下面的键查找 gzip JSON 分片：

- 同投：届次 × character/music。
- 跨部门同投：届次。
- 实体问卷：届次 × 类别 × 问题。

分片最多包含 2,000 行，生成过程最多缓冲 20,000 行；保留原始字符串、空值、零、长整数和来源字段。生成文件按稳定内容哈希命名，生成器清理不再引用的内容文件，重建不会累计快照。浏览器逐片校验 SHA-256，只缓存最近两个选择，退出大表视图后释放缓存；丢失或损坏不会退回下载整个原表。

## 原始大文件

本地 `vote_explorer/data/analysis_covote_pairs_all.csv` 可以保留，但不提交。仓库内的 `.parts.json` 以及它明确引用的四个 `.bundle-*` 是完整来源；桌面读取器直接读取分卷。需要完整 CSV 时：

```powershell
python -c "from pathlib import Path; from vote_explorer.data_chunks import merge_parts; merge_parts(Path('vote_explorer/data/analysis_covote_pairs_all.csv'))"
```

评论原文 `data_processed/character_comments/comments.csv.gz` 使用二进制分卷，原始 gzip 字节可精确恢复。原文件忽略提交，提交 `.binary-parts.json` 和 `.binpart`：

```powershell
python scripts_pipeline/split_binary_archive.py split data_processed/character_comments/comments.csv.gz
python scripts_pipeline/split_binary_archive.py restore data_processed/character_comments/comments.csv.gz.binary-parts.json
```

评论生成脚本会自动更新大归档的二进制分卷。恢复过程校验每卷及完整文件的 SHA-256，验证失败保留已有原文件。CSV 分卷不能拼接这些二进制归档分卷，两者使用不同的 manifest 格式。

`.gitattributes` 禁止生成数据的换行转换，确保 Windows 工作区、Git blob 和新 checkout 的 manifest hash 一致。

## Windows

两个现有 BAT 入口均调用 `stage_desktop_data.py`，校验当前 manifest 并仅打包一份逻辑数据，不重复嵌入完整同投 CSV 和它的分卷。本地分析数据仍完整保留。单文件版启动时需要解压整份桌面数据；网页分片不是桌面数据的替代品。

## 固定验证

```powershell
python -m pytest -q tests/test_web_shards.py
node --test tests/test_web_shards.cjs tests/test_vote_explorer_web_research.mjs
$env:PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers"
$env:WEB_ROOT="$PWD/dist/pages"
node tests/test_web_shards_browser.cjs
python tests/check_desktop_split_data.py
```

浏览器验证断言：首页不请求任何重分片；评论模板不请求同投；100 节点网络只请求 CN11 角色分片且 JS 堆小于 512 MiB；跨届缓存不超过两个选择；矩阵 CSV 有 100 行；问卷、跨部门视图和恢复默认成功。桌面验证使用实际打包暂存数据，禁止存在完整同投 CSV，检查排行、评论、100 节点网络、100×100 矩阵及 CSV 导出。

离线全量快照构建仍需要约 6 GB 工作内存。这与浏览器加载预算不同；不要在低内存设备上运行全量构建。
