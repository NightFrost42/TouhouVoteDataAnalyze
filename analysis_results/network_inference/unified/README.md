# 统一网络统计输出

本目录由 `scripts_pipeline/network_inference_output.py` 从已完成的统计脚本结果生成；
它不重新计算效应量、p 值或多重校正。CSV/JSON/Markdown 是审计主输出，`figures/` 只是可选展示。

- `hypothesis_tests.csv`：结构假设检验；
- `matrix_correlations.csv`：带同步节点置换的矩阵相关；
- `mrqap_coefficients.csv`：MRQAP/QAP 系数；
- `sensitivity_scan.csv`：实际提供的敏感性场景（无场景时仅保留表头并在摘要警告）；
- `analysis_summary.md`：由结果表和配置生成的摘要；
- `model_run_manifest.json`：输入/输出哈希、参数和来源运行清单。

共同投票不等于 CP 或原作关系；空白不等于真实 0；显著性不等于因果关系；不同届次和地区的投票规则可能不同；部分同投数据为公开关联列表而非完整矩阵。
