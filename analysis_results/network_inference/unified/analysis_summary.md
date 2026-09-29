# 网络统计分析审计摘要

以下数值直接来自同目录 CSV；表格和运行清单是审计依据，图片不是。

## 数据范围与缺失政策

- 地区：cn, jp
- 届次：CN10, CN11, CN11_VS_CN10, JP11, JP12, JP13, JP14, JP15, JP16, JP17, JP18, JP19, JP20, JP21, JP22, JP22_VS_JP21
- 结果范围：common_observed_pairs_only (94), complete_matrix (164), complete_matrix_source; model_complete_cases_reported_separately (112), partial_matrix_observed_only (120)
- 缺失政策：`exclude_unknown_no_zero_fill`；每行另存 `missing_policy`。

## 指标解释

- 假设检验的效应量为 Cliff's delta，`p_value` 为节点属性置换原始 p；已提供的 `q_value` 沿用上游 Holm 校正及其 `adjustment_family`。
- 矩阵相关的效应量为 Pearson 或 Spearman 相关；`p_value` 来自同步节点置换。
- MRQAP 效应量为模型系数；`p_value` 为 QAP 置换 p，普通回归 p 保留在 `ordinary_p`，不混用。
- `q_value` 空白且 `adjustment_method=not_applied` 表示该来源未提供多重校正；不是 q=0。

## 结果（每行均可在对应 CSV 中凭 result_id 检索）

| 表 | result_id | 地区/届次 | 指标/特征 | 有效 pair | 效应量 | p 值 | 校正值 q | 校正方式 | 状态 |
|---|---|---|---|---:|---:|---:|---:|---|---|
| `hypothesis_tests.csv` | `ni_82d7aa76c2cb4b4cec09abe2` | cn/CN10 | conditional_rate / 角色类型相同 | 12720 | 0.02721545512935508 | 0.75 | 0.75 | holm | tested |
| `hypothesis_tests.csv` | `ni_b80f374b67beed4afaf54294` | cn/CN10 | conditional_rate / 首次作品相同 | 12720 | 0.6221406012335906 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_14ccb37e517b1b4bb7f4415d` | cn/CN10 | conditional_rate / 区域相同 | 406 | 0.6132542037586548 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_c1eb9ab2a401eff0a9fa5f58` | cn/CN10 | conditional_rate / 来源组相同 | 12720 | 0.2894644217495579 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_1c2646883675fc949117d32c` | cn/CN10 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_c051092ad1c22c07ad691ef1` | cn/CN10 | intersection_count / 角色类型相同 | 12720 | 0.25561268257824654 | 0.1 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_08ab4e8e9ea5ca7636fec2b9` | cn/CN10 | intersection_count / 首次作品相同 | 12720 | 0.41242141465773674 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_afa19ed336288f0b1cff2e65` | cn/CN10 | intersection_count / 区域相同 | 406 | 0.33513955188577826 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_9b6d487716a08d9518b17c51` | cn/CN10 | intersection_count / 来源组相同 | 12720 | 0.36857173699377843 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_76047a7fb5f05bc5278a6e75` | cn/CN10 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_3a747a4bad85994986bde8ff` | cn/CN10 | jaccard / 角色类型相同 | 12720 | 0.30403105465532776 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_8ac0a0608332ca574846cc27` | cn/CN10 | jaccard / 首次作品相同 | 12720 | 0.6269805059720808 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_32cf7755d86e539bfa27d2a6` | cn/CN10 | jaccard / 区域相同 | 406 | 0.5669375994495334 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_a6719960ce10b77ee834d325` | cn/CN10 | jaccard / 来源组相同 | 12720 | 0.39236516163943924 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_09dfc5161496fac0c8ad16ed` | cn/CN10 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_e84d9691719413951c296982` | cn/CN10 | share / 角色类型相同 | 12720 | 0.25561268257824654 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_92cd6fe89b8460b12970653c` | cn/CN10 | share / 首次作品相同 | 12720 | 0.41242141465773674 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_c6f968fc07ae0dfb70ff73f7` | cn/CN10 | share / 区域相同 | 406 | 0.33513955188577826 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_657567a4a2a1105d267a5072` | cn/CN10 | share / 来源组相同 | 12720 | 0.36857173699377843 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_d1c39baee19a6e91bd891212` | cn/CN10 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_c7e0142a8ddf8553a449ca01` | cn/CN11 | conditional_rate / 角色类型相同 | 13530 | 0.03918012845457408 | 0.7 | 0.7 | holm | tested |
| `hypothesis_tests.csv` | `ni_35982c2460bfa2a6cb754e0b` | cn/CN11 | conditional_rate / 首次作品相同 | 13530 | 0.5842172656722648 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_020fc073e673c30f1c9112ec` | cn/CN11 | conditional_rate / 区域相同 | 496 | 0.6418992884510126 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_70e13e88e39d0e54d7195633` | cn/CN11 | conditional_rate / 来源组相同 | 13530 | 0.28848576159137673 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_84697fd1466f04d10daac05c` | cn/CN11 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_886208cee70ee04748849630` | cn/CN11 | intersection_count / 角色类型相同 | 13530 | 0.2278352696441759 | 0.15 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_484fed9fe6b2cb50e178ab39` | cn/CN11 | intersection_count / 首次作品相同 | 13530 | 0.39825388553404895 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_d6afbf920736d5ddb749a7c5` | cn/CN11 | intersection_count / 区域相同 | 496 | 0.45301039956212374 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_3b16aed3a06291e79b6ee940` | cn/CN11 | intersection_count / 来源组相同 | 13530 | 0.3358204800175506 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_f62ae78eae152f918a50c27f` | cn/CN11 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_9ba2e86510996a90530fccf8` | cn/CN11 | jaccard / 角色类型相同 | 13530 | 0.27905020538472236 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_c6054eb03591c92dfc6331f8` | cn/CN11 | jaccard / 首次作品相同 | 13530 | 0.583340994045763 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_6424d010960a50886cf4459e` | cn/CN11 | jaccard / 区域相同 | 496 | 0.6683360700602079 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_2778842f5a96a0a48421289e` | cn/CN11 | jaccard / 来源组相同 | 13530 | 0.35828757194288086 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_c42e437ff364af9f4f4491a1` | cn/CN11 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_2823687d6ce2fa8fa694c98c` | cn/CN11 | share / 角色类型相同 | 13530 | 0.2278352696441759 | 0.1 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_38657c392d9e2b65ca3966b7` | cn/CN11 | share / 首次作品相同 | 13530 | 0.39825388553404895 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_aa042ff8675a2cdcc0bc05e9` | cn/CN11 | share / 区域相同 | 496 | 0.45301039956212374 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_d517bf4b0e637170f3a998ef` | cn/CN11 | share / 来源组相同 | 13530 | 0.3358204800175506 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_7693bc0ac0a87b8509eaf1dc` | cn/CN11 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_4b37eeb2029bf2b31dee211e` | jp/JP11 | conditional_rate / 角色类型相同 | 1118 | -0.10150628566702502 | 0.3 | 0.3 | holm | tested |
| `hypothesis_tests.csv` | `ni_9b14d0b6cb847e24688d738f` | jp/JP11 | conditional_rate / 首次作品相同 | 1118 | 0.36855826887981236 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_8fbe2edea0cbc99fcfe68a5d` | jp/JP11 | conditional_rate / 区域相同 | 33 | 0.6033057851239669 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_9d60cde99dc0d12d7c6bc026` | jp/JP11 | conditional_rate / 来源组相同 | 1118 | 0.12076506439208656 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_67c6a3c716e58999acef968f` | jp/JP11 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_516c2f0a255e5ca253affa84` | jp/JP11 | intersection_count / 角色类型相同 | 1118 | -0.04096021834422292 | 0.8 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_9e0e685731f90a3a1d7210af` | jp/JP11 | intersection_count / 首次作品相同 | 1118 | 0.09820109498566088 | 0.15 | 0.44999999999999996 | holm | tested |
| `hypothesis_tests.csv` | `ni_69730fa17e1c672362640077` | jp/JP11 | intersection_count / 区域相同 | 33 | -0.11157024793388426 | 0.75 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_dfd48f88cd7b044cbfd57fbb` | jp/JP11 | intersection_count / 来源组相同 | 1118 | 0.30367643645945286 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_0a0716ee55120be41f304e5f` | jp/JP11 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_34d350ea7ae205f3566135de` | jp/JP11 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_3e6aac2dd18b53ffe1463c96` | jp/JP11 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_ff3ddbaae07795edf0df8101` | jp/JP11 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_8175edf860aabcde8d5e9d59` | jp/JP11 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_bbc4c39c390b799c3c5fd0ad` | jp/JP11 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5ee1f1ea542d3fe0079368fd` | jp/JP11 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_ef3511d25bed30b8cd587b3c` | jp/JP11 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5836759497ef9096ba590dc1` | jp/JP11 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_229c899b283327e9fe9236dd` | jp/JP11 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_bfd90d4d185119aaa57542b7` | jp/JP11 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_32d5bfb9702b32edf9e0dbc1` | jp/JP12 | conditional_rate / 角色类型相同 | 1471 | -0.3168403074295474 | 0.25 | 0.5 | holm | tested |
| `hypothesis_tests.csv` | `ni_9fd40a7c12c1b27bc3ae8bff` | jp/JP12 | conditional_rate / 首次作品相同 | 1471 | 0.20334494773519163 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_d8945357c4f4581badf3eb5b` | jp/JP12 | conditional_rate / 区域相同 | 35 | 0.10400000000000009 | 0.75 | 0.75 | holm | tested |
| `hypothesis_tests.csv` | `ni_1b360f04c335a02261a2c37b` | jp/JP12 | conditional_rate / 来源组相同 | 1471 | 0.1144526969438695 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_3304ea3159c9c4922f606672` | jp/JP12 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_31e1c3288aa7a065605a4bcf` | jp/JP12 | intersection_count / 角色类型相同 | 1471 | 0.027184742385425453 | 0.95 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_d57ea563ab2a3b515769ae6f` | jp/JP12 | intersection_count / 首次作品相同 | 1471 | 0.007871246059399262 | 0.95 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_3be891508be5ebd93f828e44` | jp/JP12 | intersection_count / 区域相同 | 35 | -0.20799999999999996 | 0.4 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_cb447d68c0255516d9a29d00` | jp/JP12 | intersection_count / 来源组相同 | 1471 | 0.35120337676042057 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_297b187ae4435c02afb6db26` | jp/JP12 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_968cd05248ffb2f904187ec4` | jp/JP12 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_917456656cf9f869dbabed27` | jp/JP12 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_a6fdf77cb1b4a5a5985bd1e5` | jp/JP12 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_ec76f0c15c1569497cd0a536` | jp/JP12 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_f721f02776a54309d4fc8979` | jp/JP12 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_69bd43ee86bfaedd1e2224f5` | jp/JP12 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_26722203324f5a5f5d89ee90` | jp/JP12 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_a730345c057df4d8a6c9c36b` | jp/JP12 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_33014c5a506a676445124d29` | jp/JP12 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5957e5d5e6e451a62fb46bfd` | jp/JP12 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_31587c6a9af757a9d1270377` | jp/JP13 | conditional_rate / 角色类型相同 | 1427 | -0.18945205152101707 | 0.15 | 0.44999999999999996 | holm | tested |
| `hypothesis_tests.csv` | `ni_d3c1ecbf84439ff31ef10f83` | jp/JP13 | conditional_rate / 首次作品相同 | 1427 | 0.2208275740575114 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_055399fe10fb48002c8a09c6` | jp/JP13 | conditional_rate / 区域相同 | 42 | 0.36604774535809015 | 0.2 | 0.44999999999999996 | holm | tested |
| `hypothesis_tests.csv` | `ni_db06bd6a799fa18232dc0372` | jp/JP13 | conditional_rate / 来源组相同 | 1427 | 0.08305954825462014 | 0.15 | 0.44999999999999996 | holm | tested |
| `hypothesis_tests.csv` | `ni_76eb7d0644685b53ad395b1f` | jp/JP13 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_89c68e107b22193287e92e6e` | jp/JP13 | intersection_count / 角色类型相同 | 1427 | 0.0644669868807799 | 0.75 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_5afbbfd3f1ec858d603be0c7` | jp/JP13 | intersection_count / 首次作品相同 | 1427 | 0.043553676450659884 | 0.55 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_b6409f4daefd6dfa7dcad275` | jp/JP13 | intersection_count / 区域相同 | 42 | -0.01326259946949604 | 0.85 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_85798397f26fab103c5d02e6` | jp/JP13 | intersection_count / 来源组相同 | 1427 | 0.3475752544890558 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_985e1dc26955422c49aa0031` | jp/JP13 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_87a2432b17e824a249559f16` | jp/JP13 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d76cca08fee948060f876be7` | jp/JP13 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_8981afc5d6c7317d535f94b3` | jp/JP13 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_692efea223954982d95d313e` | jp/JP13 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_28cb899cd27d26086ceb644a` | jp/JP13 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_e85605d9015723330a9a6941` | jp/JP13 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_6b982b10947cadc4772bbdf2` | jp/JP13 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_4bbf50956fb00c1e53debfaf` | jp/JP13 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_3f3f91fd9f86e020c0676fef` | jp/JP13 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_7daead37a8377d5fabb09975` | jp/JP13 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5d67145620dda15ec6bd45a1` | jp/JP14 | conditional_rate / 角色类型相同 | 1373 | -0.18679412634276138 | 0.2 | 0.4 | holm | tested |
| `hypothesis_tests.csv` | `ni_51e12740f8d2d2c1885d9c46` | jp/JP14 | conditional_rate / 首次作品相同 | 1373 | 0.30118881583316726 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_9539cb2dae63a55e6b698a64` | jp/JP14 | conditional_rate / 区域相同 | 42 | 0.24489795918367352 | 0.35 | 0.4 | holm | tested |
| `hypothesis_tests.csv` | `ni_e209e083476d4e5afa4d379e` | jp/JP14 | conditional_rate / 来源组相同 | 1373 | 0.0935901830396928 | 0.1 | 0.30000000000000004 | holm | tested |
| `hypothesis_tests.csv` | `ni_dcdc4dafdfe72412ce20e4aa` | jp/JP14 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d7a8ac0608acc11973a04202` | jp/JP14 | intersection_count / 角色类型相同 | 1373 | 0.02803127361124802 | 0.85 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_bc8c25e7a2bd1b4ad019a3e4` | jp/JP14 | intersection_count / 首次作品相同 | 1373 | 0.05375499029613384 | 0.55 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_d57683303edd72d63cd3596b` | jp/JP14 | intersection_count / 区域相同 | 42 | -0.25255102040816324 | 0.35 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_a8f76324e2dea50f9bfd5d3d` | jp/JP14 | intersection_count / 来源组相同 | 1373 | 0.3130641438723978 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_f59b4208ee775970a7b9e37b` | jp/JP14 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_27beeafb08bc5c363948799e` | jp/JP14 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_179d96f1052f95de1eed7870` | jp/JP14 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_28f2250232611775cd11abf0` | jp/JP14 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_35861469883e12b859b82e5a` | jp/JP14 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_18bbfa65892a786479698210` | jp/JP14 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_94d58e53391df1a2b26d2233` | jp/JP14 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_bc1e5600174ff05138da26bf` | jp/JP14 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_870f13c85f2a5ef2e35a4284` | jp/JP14 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_173236860c806360f6b9ab16` | jp/JP14 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_f2281a7b5709892529c74011` | jp/JP14 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_2c8f6747cc12e317471df245` | jp/JP15 | conditional_rate / 角色类型相同 | 1374 | -0.1610769441880192 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_2c228154219e618f5cb9da77` | jp/JP15 | conditional_rate / 首次作品相同 | 1374 | 0.31278638969273587 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_bd5ec97efb66101bb3455547` | jp/JP15 | conditional_rate / 区域相同 | 37 | 0.22222222222222232 | 0.3 | 0.3 | holm | tested |
| `hypothesis_tests.csv` | `ni_006bd7cb7b3353ec776d45f1` | jp/JP15 | conditional_rate / 来源组相同 | 1374 | 0.12067611507090903 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_b55f2d68033ba75895575a63` | jp/JP15 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_8c9b48ab6f51161327c95402` | jp/JP15 | intersection_count / 角色类型相同 | 1374 | 0.07640777425712941 | 0.5 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_dd538d4f745f8379aab9a246` | jp/JP15 | intersection_count / 首次作品相同 | 1374 | 0.04417451569498465 | 0.55 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_b7ae12f553ffc18efcdd6412` | jp/JP15 | intersection_count / 区域相同 | 37 | -0.2962962962962963 | 0.3 | 0.8999999999999999 | holm | tested |
| `hypothesis_tests.csv` | `ni_6fcd95d50ddd95f95c517c98` | jp/JP15 | intersection_count / 来源组相同 | 1374 | 0.32976798442207356 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_e30643482848404f989b5d64` | jp/JP15 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_2d54b50b1138804d4ddd2a95` | jp/JP15 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_e5284b3398ab41ad2dd4022c` | jp/JP15 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_56206143281294c1bc0d64a4` | jp/JP15 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_708bdfd8c9cbf2c61b00d324` | jp/JP15 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_cae8cb76790f89abb31a4307` | jp/JP15 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_54d4ce0ce4d9732613bca6f8` | jp/JP15 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d7728fc2f16fb361591860c6` | jp/JP15 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_0ddfe31b6d1bac967bd3a289` | jp/JP15 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_a7a4a6a7623cd88809691742` | jp/JP15 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_fac3014356b9d4f9064bab8c` | jp/JP15 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_cc747647990e9f8ed17a0c1b` | jp/JP16 | conditional_rate / 角色类型相同 | 1475 | -0.11503273679615889 | 0.4 | 0.6000000000000001 | holm | tested |
| `hypothesis_tests.csv` | `ni_ac1a316605573efe9a089fd7` | jp/JP16 | conditional_rate / 首次作品相同 | 1475 | 0.260882425127279 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_b983714af9aa452b36a82c0b` | jp/JP16 | conditional_rate / 区域相同 | 53 | 0.26538461538461533 | 0.2 | 0.6000000000000001 | holm | tested |
| `hypothesis_tests.csv` | `ni_2a878699da8c54a1222d03c6` | jp/JP16 | conditional_rate / 来源组相同 | 1475 | 0.05341787225964012 | 0.3 | 0.6000000000000001 | holm | tested |
| `hypothesis_tests.csv` | `ni_80e4e7620038777329b1f8eb` | jp/JP16 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_ae6298e359cc867ffa23510a` | jp/JP16 | intersection_count / 角色类型相同 | 1475 | 0.04366361123235851 | 0.95 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_ceaaf8432a23c4d0861406b8` | jp/JP16 | intersection_count / 首次作品相同 | 1475 | 0.014250832268742464 | 0.85 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_769e84666c0b467e22a14f9c` | jp/JP16 | intersection_count / 区域相同 | 53 | -0.15000000000000002 | 0.5 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_b11a6e0ba6e9fe04f5013960` | jp/JP16 | intersection_count / 来源组相同 | 1475 | 0.27500463827896127 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_4519d95ff2af0b5ab2af5288` | jp/JP16 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_e04944aa8e0acff388b1809c` | jp/JP16 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_ff8a5e8ff0aa46f0b19f75fb` | jp/JP16 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_29573a426c0ad5b3cdee8de3` | jp/JP16 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d092b784b6879bda8fe63a54` | jp/JP16 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_7aa6adf9cd21bf98b96b60c0` | jp/JP16 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d197c9703f5363feea25f425` | jp/JP16 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5d0f0b71a20ca173c205b44e` | jp/JP16 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_3fc8c4c7040cd135151db6fc` | jp/JP16 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5fd6b5ff2bccdfdfc5a2dd5b` | jp/JP16 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_149cece43cde00f6ff6a585c` | jp/JP16 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_0bc5a2e910a8f14d3acfa1fe` | jp/JP17 | conditional_rate / 角色类型相同 | 1592 | -0.25877414702281554 | 0.15 | 0.44999999999999996 | holm | tested |
| `hypothesis_tests.csv` | `ni_8f6378a52439b2005bd27888` | jp/JP17 | conditional_rate / 首次作品相同 | 1592 | 0.15271078366591784 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_e9710d54b3a10ca65d861201` | jp/JP17 | conditional_rate / 区域相同 | 57 | 0.2195121951219512 | 0.35 | 0.7 | holm | tested |
| `hypothesis_tests.csv` | `ni_c948a49e10b8e7b419a88e22` | jp/JP17 | conditional_rate / 来源组相同 | 1592 | 0.04385144991498424 | 0.8 | 0.8 | holm | tested |
| `hypothesis_tests.csv` | `ni_289dbf8c53405f9164fef960` | jp/JP17 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_2c23b32f93c5d19ad750bdb8` | jp/JP17 | intersection_count / 角色类型相同 | 1582 | 0.0011857583419669915 | 1.0 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_978d95c1d118707ed0ec9979` | jp/JP17 | intersection_count / 首次作品相同 | 1582 | 0.02035853310478175 | 0.85 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_ba90201d65af21768766169b` | jp/JP17 | intersection_count / 区域相同 | 57 | -0.2515243902439024 | 0.4 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_841951690729eae62b06f20e` | jp/JP17 | intersection_count / 来源组相同 | 1582 | 0.3161759184163888 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_8c17222956414bcd993a90e3` | jp/JP17 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5642b983c270028d8a6f87f7` | jp/JP17 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_cb9294261f564bb248b4589c` | jp/JP17 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_c08eb925494e54a6acac5d10` | jp/JP17 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_01e1c7ad3785e437abc543b5` | jp/JP17 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5490a9fee8c3ebf6a511e268` | jp/JP17 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_0a4ebdf5fa1fe6db2a16a375` | jp/JP17 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_11c5638e747691536bfcf297` | jp/JP17 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_bc03943d7cc3d1e6c23c2e0d` | jp/JP17 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_ead37561d33e42e244d0f26b` | jp/JP17 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d055a9089255aa714237ec54` | jp/JP17 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_f74d1324e7a89da42d4f5761` | jp/JP18 | conditional_rate / 角色类型相同 | 1638 | -0.31514475903986117 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_574b2fa9118dad3a927f50c5` | jp/JP18 | conditional_rate / 首次作品相同 | 1638 | 0.17521037463976952 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_0f95a89f617baf37a19057b5` | jp/JP18 | conditional_rate / 区域相同 | 52 | 0.12661498708010344 | 0.7 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_29fe4d151416d528c2bd9333` | jp/JP18 | conditional_rate / 来源组相同 | 1638 | 0.0397597691558893 | 0.55 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_8260f1298a244d9757dc4dd0` | jp/JP18 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_392e08b389ea05bc7475fad1` | jp/JP18 | intersection_count / 角色类型相同 | 1635 | 0.04345081715513999 | 0.75 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_2e0c8ba23247ee3a2d7da826` | jp/JP18 | intersection_count / 首次作品相同 | 1635 | 0.08384596599762784 | 0.45 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_680c356fe996c6432b91bdda` | jp/JP18 | intersection_count / 区域相同 | 52 | 0.06459948320413433 | 0.7 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_91770e5372b76b7f5e38aa83` | jp/JP18 | intersection_count / 来源组相同 | 1635 | 0.33269193899782135 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_1e3b6d634cd0e5af60436909` | jp/JP18 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d0e85dabe8d9fdf151c6e2b3` | jp/JP18 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_b259dea2a4e6667a230416de` | jp/JP18 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_24dcdb0609c0597789e3adf4` | jp/JP18 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_fa4c4c400aed2112eb12f170` | jp/JP18 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_99f2ed433da48b22b679e4bb` | jp/JP18 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_b7993ed93e4ff9f92fa1007e` | jp/JP18 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_c87ec91ea90aeba0629418fa` | jp/JP18 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_780848ef730e867cb4e3fc5a` | jp/JP18 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_4f455bc798d8ee009f39180c` | jp/JP18 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_7dd0c8f0d7495105afcc448c` | jp/JP18 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_488829f9ba46090b551f4024` | jp/JP19 | conditional_rate / 角色类型相同 | 1697 | -0.36860086638106404 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_29e4c273daefd882c6031b81` | jp/JP19 | conditional_rate / 首次作品相同 | 1697 | 0.14478809805867732 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_844f7e0090d8ef4e7ac79159` | jp/JP19 | conditional_rate / 区域相同 | 66 | 0.13788098693759077 | 0.55 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_5ecdfab22056c6cda78e338b` | jp/JP19 | conditional_rate / 来源组相同 | 1697 | 0.027675949530478583 | 0.8 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_ffd255b21b5bce4a59a81fc5` | jp/JP19 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_282c83e9d180b2db74879766` | jp/JP19 | intersection_count / 角色类型相同 | 1641 | 0.03953985791864478 | 0.65 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_40006b5769df2fe286cd4019` | jp/JP19 | intersection_count / 首次作品相同 | 1641 | 0.02041912629298248 | 0.9 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_17d9fa70883e34dcd33a40d1` | jp/JP19 | intersection_count / 区域相同 | 63 | -0.07692307692307687 | 0.85 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_f10d71fcc31e909de54ebb19` | jp/JP19 | intersection_count / 来源组相同 | 1641 | 0.2856431301083897 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_650fc06501b21eae706ea973` | jp/JP19 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_9dffb7585da1bbd9385f0931` | jp/JP19 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_11393c9c6c15ac4bd0b4463d` | jp/JP19 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_c06452cc065ac78ae723ec9e` | jp/JP19 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_bbf1770146643b5153bede8f` | jp/JP19 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_68ac7c82ddf006e5e6df70d6` | jp/JP19 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5636dcee08877f727bdadf4e` | jp/JP19 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_1c425abda887bf92711253dd` | jp/JP19 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_5f1b417e7aba22964ef6710d` | jp/JP19 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_c792f09fde2ddb9eff63c546` | jp/JP19 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_b626db10640e6f173248b989` | jp/JP19 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d0c17c925720ea3dba4fd771` | jp/JP20 | conditional_rate / 角色类型相同 | 1709 | -0.3930148981168593 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_3fac8d4e2aa4f9a4a9989ec3` | jp/JP20 | conditional_rate / 首次作品相同 | 1709 | 0.13631595644520855 | 0.1 | 0.30000000000000004 | holm | tested |
| `hypothesis_tests.csv` | `ni_6a306bea3ce4d3ecb3d555f2` | jp/JP20 | conditional_rate / 区域相同 | 67 | 0.26068376068376065 | 0.2 | 0.4 | holm | tested |
| `hypothesis_tests.csv` | `ni_3a08f37694b933c6fecba394` | jp/JP20 | conditional_rate / 来源组相同 | 1709 | -0.0011263916175507926 | 1.0 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_f8bdf41dbf9b2d0f959f6dd7` | jp/JP20 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_27e00dee7199cfcceb588b34` | jp/JP20 | intersection_count / 角色类型相同 | 1709 | 0.027860805231900265 | 0.9 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_e9509b3a173961d71ed5eebe` | jp/JP20 | intersection_count / 首次作品相同 | 1709 | 0.03900589463342752 | 0.6 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_51ab53d833287daeba770414` | jp/JP20 | intersection_count / 区域相同 | 67 | -0.01139601139601143 | 1.0 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_a9620ef49f5e30c0205efc5b` | jp/JP20 | intersection_count / 来源组相同 | 1709 | 0.20773248199083172 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_55cafacf56168c42169b0ea8` | jp/JP20 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d6c0a667ba47b028991b562f` | jp/JP20 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_52229eec89ab8850f7340aa8` | jp/JP20 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_2df062e78398743b2a3298c4` | jp/JP20 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_a6699d62bfa09e92ad57cbe9` | jp/JP20 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_e0efd3a48e904420b85d6767` | jp/JP20 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_a7be53186633d489a1ab28b6` | jp/JP20 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_4761eb0348b2d62dd400a15c` | jp/JP20 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_26745f06055f28c6167947e7` | jp/JP20 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_13fc7b68d4624c81b6fe27e8` | jp/JP20 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_aa29dc08945e5408c7718eb5` | jp/JP20 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_fb1b008b04b727e6d24b6d4b` | jp/JP21 | conditional_rate / 角色类型相同 | 1719 | -0.2795645387016902 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_f08ae12bc6cdac9409bcd4b7` | jp/JP21 | conditional_rate / 首次作品相同 | 1719 | 0.1679062126642772 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_3f72b08c6e563a4aafa830f8` | jp/JP21 | conditional_rate / 区域相同 | 64 | 0.4262820512820513 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_f719571ab9c4b9c2e41ffa6d` | jp/JP21 | conditional_rate / 来源组相同 | 1719 | -0.006639403492840978 | 0.95 | 0.95 | holm | tested |
| `hypothesis_tests.csv` | `ni_66d0385a5d31a791f693349d` | jp/JP21 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_330eca1b65c9534d9f13d64b` | jp/JP21 | intersection_count / 角色类型相同 | 1677 | 0.037784025017395306 | 0.85 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_07f94272b322ea0569ee9541` | jp/JP21 | intersection_count / 首次作品相同 | 1677 | 0.012623795354620881 | 0.95 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_d363838c3d72fec778903036` | jp/JP21 | intersection_count / 区域相同 | 62 | -0.09166666666666667 | 0.35 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_4160140da6667ccb26272d14` | jp/JP21 | intersection_count / 来源组相同 | 1677 | 0.17869880254235593 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_dcdf237b62ae873978e35b48` | jp/JP21 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_fdf821a90c7d8eb181622e6f` | jp/JP21 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_01524bec1585a40fef424aee` | jp/JP21 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_cd371570b2e75602b81e1c27` | jp/JP21 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_4790bce8d852366015666b06` | jp/JP21 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_bd145d96490876dc0a02e744` | jp/JP21 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_db1217e2301785b11ad37931` | jp/JP21 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_0fd42ba29151152436ad2fc1` | jp/JP21 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_d2625dea821ebcdab5340f7f` | jp/JP21 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_513c946658d2c9990eac93f6` | jp/JP21 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_dbd780b1022567b6587343c9` | jp/JP21 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_0ed7fc123c88316e53e04fd3` | jp/JP22 | conditional_rate / 角色类型相同 | 1675 | -0.2657008371608196 | 0.1 | 0.30000000000000004 | holm | tested |
| `hypothesis_tests.csv` | `ni_cda06d8cdade3640e61733a7` | jp/JP22 | conditional_rate / 首次作品相同 | 1675 | 0.16833033714952528 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_63052b0809a5f7d81f176e57` | jp/JP22 | conditional_rate / 区域相同 | 61 | 0.2981818181818181 | 0.2 | 0.4 | holm | tested |
| `hypothesis_tests.csv` | `ni_d2e2e500d13d6ee9076a7f67` | jp/JP22 | conditional_rate / 来源组相同 | 1675 | 0.0066543816543815915 | 0.95 | 0.95 | holm | tested |
| `hypothesis_tests.csv` | `ni_60434ceb28b15ce09fbee6b6` | jp/JP22 | conditional_rate / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_7d6b7cf08998b7c331f0e6fb` | jp/JP22 | intersection_count / 角色类型相同 | 1672 | 0.039290007605309096 | 0.8 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_70d235b577d8db1431abd14f` | jp/JP22 | intersection_count / 首次作品相同 | 1672 | 0.054323316737633354 | 0.55 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_e7f59c730fb1179a615c6bca` | jp/JP22 | intersection_count / 区域相同 | 61 | -0.10181818181818181 | 0.65 | 1.0 | holm | tested |
| `hypothesis_tests.csv` | `ni_18de47b179496721e776b701` | jp/JP22 | intersection_count / 来源组相同 | 1672 | 0.18908435314685312 | 0.05 | 0.2 | holm | tested |
| `hypothesis_tests.csv` | `ni_ecc645c4c3d526dd1dcb9afd` | jp/JP22 | intersection_count / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_0043b7d6fd7d7538027cd1f5` | jp/JP22 | jaccard / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_e6cb682a7e03dd40b9f48600` | jp/JP22 | jaccard / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_11036cd62cba6d770197c9e4` | jp/JP22 | jaccard / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_f6bc026a18a5a920b589978f` | jp/JP22 | jaccard / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_71b787a6d23de842ea2c745f` | jp/JP22 | jaccard / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_8bc8d4086be9427981894efc` | jp/JP22 | share / 角色类型相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_9e0d3af924127d95d60679fe` | jp/JP22 | share / 首次作品相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_73925a1fe71e3dd25b522c42` | jp/JP22 | share / 区域相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_b17e6998f55d9b81ab2af680` | jp/JP22 | share / 来源组相同 | 0 | — | — | — | holm | not_estimable |
| `hypothesis_tests.csv` | `ni_e0f823d26e851d340e55f52a` | jp/JP22 | share / 关卡相同 | 0 | — | — | — | holm | not_estimable |
| `matrix_correlations.csv` | `ni_6c593cb4d2253f5958eb2640` | cn/CN10 | lift / lift 与 cosine 的矩阵相关 | 26106 | 0.9071626872544101 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_943065f9968d88da25b7bf77` | cn/CN10 | lift / lift 与 cosine 的矩阵相关 | 26106 | 0.429887260413985 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_ddde9516d3fc99cce804f05c` | cn/CN10 | raw_count / raw_count 与 cosine 的矩阵相关 | 26106 | 0.9555937008604066 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_6077e0dafe12e0e040431100` | cn/CN10 | raw_count / raw_count 与 cosine 的矩阵相关 | 26106 | 0.6237911519467102 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_44e90a576301ceca592f2098` | cn/CN10 | raw_count / raw_count 与 lift 的矩阵相关 | 26106 | 0.8097472765395201 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_2bb33040d5fc011dedcb7192` | cn/CN10 | raw_count / raw_count 与 lift 的矩阵相关 | 26106 | -0.006475270304927657 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_c9f51ed9b4350ce265a9cc3d` | cn/CN10 | raw_count / raw_count 与 vote_count 的矩阵相关 | 572 | 0.29608478363425206 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_463cc81a61127925129417d4` | cn/CN10 | raw_count / raw_count 与 vote_count 的矩阵相关 | 572 | 0.5179040284372611 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_c32caacbcf1321d3bd44d850` | cn/CN10 | lift / lift 与 cosine 的矩阵相关 | 172578 | 0.9705678506101326 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_8c962190767788314119900c` | cn/CN10 | lift / lift 与 cosine 的矩阵相关 | 172578 | 0.414667286615833 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_b4ca6fbbaf80a8c87fd7b74a` | cn/CN10 | raw_count / raw_count 与 cosine 的矩阵相关 | 172578 | 0.9724714842512673 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_1f93d5b231892e71ca13f128` | cn/CN10 | raw_count / raw_count 与 cosine 的矩阵相关 | 172578 | 0.6178369133208065 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_cc567831ef782ce212bcceae` | cn/CN10 | raw_count / raw_count 与 lift 的矩阵相关 | 172578 | 0.9180124639944238 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_59f105511258688283644369` | cn/CN10 | raw_count / raw_count 与 lift 的矩阵相关 | 172578 | -0.003205950915160166 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_baca0f636d2f65b1b811a033` | cn/CN11 | lift / lift 与 cosine 的矩阵相关 | 25425 | 0.9290672918762723 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_9f5d814500bbba63c3e87dde` | cn/CN11 | lift / lift 与 cosine 的矩阵相关 | 25425 | 0.5392511450508279 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_fa26fb82f4e313ea5a20e39a` | cn/CN11 | raw_count / raw_count 与 cosine 的矩阵相关 | 25425 | 0.9620472232667446 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_da9caa23a23b51d8f6ec8ab9` | cn/CN11 | raw_count / raw_count 与 cosine 的矩阵相关 | 25425 | 0.5746924427374696 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_24df1d9c4db9c35f30375693` | cn/CN11 | raw_count / raw_count 与 lift 的矩阵相关 | 25425 | 0.8454516780407794 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_f602d8de382ca1e6f7fce727` | cn/CN11 | raw_count / raw_count 与 lift 的矩阵相关 | 25425 | -0.006488068872647597 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_13005e1abcf14f221b4ea271` | cn/CN11 | raw_count / raw_count 与 vote_count 的矩阵相关 | 442 | 0.2771282580938184 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_7d328f6a423bc12b0865319a` | cn/CN11 | raw_count / raw_count 与 vote_count 的矩阵相关 | 442 | 0.5308685739058041 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_e143c2f738873f8a9e7a57cd` | cn/CN11 | lift / lift 与 cosine 的矩阵相关 | 174936 | 0.9832242426164 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_0784bf3847d5993e9932e258` | cn/CN11 | lift / lift 与 cosine 的矩阵相关 | 174936 | 0.4458995852525555 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_a5bd7ea0472ac584035d6c4b` | cn/CN11 | raw_count / raw_count 与 cosine 的矩阵相关 | 174936 | 0.9812130372086771 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_c09337c3efbec1e62ee7ad0c` | cn/CN11 | raw_count / raw_count 与 cosine 的矩阵相关 | 174936 | 0.5798527371357726 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_a9a1f5240515f69cd16e8c5b` | cn/CN11 | raw_count / raw_count 与 lift 的矩阵相关 | 174936 | 0.9492186575676209 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_fcc6b697bd55cf0671bb6393` | cn/CN11 | raw_count / raw_count 与 lift 的矩阵相关 | 174936 | -0.0006905072524403426 | 1.0 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_5f090e12d213fe6be975d9be` | cn/CN11_VS_CN10 | cosine / cosine 与 cosine 的矩阵相关 | 23436 | 0.7289902296638993 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_461fa0d9552b8fc5e70e02be` | cn/CN11_VS_CN10 | cosine / cosine 与 cosine 的矩阵相关 | 23436 | 0.7502751237460616 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_3d14bbf0830e78fc8f0be9c8` | cn/CN11_VS_CN10 | lift / lift 与 lift 的矩阵相关 | 23436 | 0.5189355563371641 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_4e85450189e0be33c9d1c0c9` | cn/CN11_VS_CN10 | lift / lift 与 lift 的矩阵相关 | 23436 | 0.05138520848041387 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_9dc5b613532f09b45f09a3cb` | cn/CN11_VS_CN10 | raw_count / raw_count 与 raw_count 的矩阵相关 | 28441 | 0.8491494723790778 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_54203a7c687bdb4d4fa777e9` | cn/CN11_VS_CN10 | raw_count / raw_count 与 raw_count 的矩阵相关 | 28441 | 0.9882094428466032 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_88aa96de2e65d8e3fbcb30e4` | cn/CN11_VS_CN10 | cosine / cosine 与 cosine 的矩阵相关 | 157641 | 0.5800183829181172 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_96a0dbafd04787de70790740` | cn/CN11_VS_CN10 | cosine / cosine 与 cosine 的矩阵相关 | 157641 | 0.6035552406886382 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_31dfe8b1458522a2434a3bf1` | cn/CN11_VS_CN10 | lift / lift 与 lift 的矩阵相关 | 157641 | 0.4612152028735759 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_573c27bda3be1c56e1037a05` | cn/CN11_VS_CN10 | lift / lift 与 lift 的矩阵相关 | 157641 | 0.03849355018586907 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_76126fbe5b85c7e1ae1f82ec` | cn/CN11_VS_CN10 | raw_count / raw_count 与 raw_count 的矩阵相关 | 169071 | 0.6963940119010866 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_517d69ecbbe1bd01b320a0c8` | cn/CN11_VS_CN10 | raw_count / raw_count 与 raw_count 的矩阵相关 | 169071 | 0.978944239668819 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_4aea7fbd55a82514c2453cdb` | cn/CN11_VS_CN10 | vote_count / vote_count 与 vote_count 的矩阵相关 | 355 | 0.8971314192037757 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_c15d133878feb8779f770cac` | cn/CN11_VS_CN10 | vote_count / vote_count 与 vote_count 的矩阵相关 | 355 | 0.9871662687521707 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_dbdec6b68cfc22174cefbf72` | jp/JP11 | raw_count / raw_count 与 lift 的矩阵相关 | 1184 | -0.09001065642593124 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_6773ee3cf89602bf80763235` | jp/JP11 | raw_count / raw_count 与 lift 的矩阵相关 | 1184 | -0.11398145798373516 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_804b7277e6e91b0073c348ff` | jp/JP11 | raw_count / raw_count 与 lift 的矩阵相关 | 1487 | -0.012624367125252342 | 1.0 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_20786a414a4f539e40d637d5` | jp/JP11 | raw_count / raw_count 与 lift 的矩阵相关 | 1487 | -0.08649045038448464 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_840934035254dd8aacf701ea` | jp/JP12 | raw_count / raw_count 与 lift 的矩阵相关 | 1710 | -0.1568336903998726 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_de097f58058f03ad2f6bdf96` | jp/JP12 | raw_count / raw_count 与 lift 的矩阵相关 | 1710 | -0.10561622062965255 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_df004c71692af29467e7633f` | jp/JP12 | raw_count / raw_count 与 lift 的矩阵相关 | 2462 | -0.12808616746042667 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_63589b9e8dc1db072723ce93` | jp/JP12 | raw_count / raw_count 与 lift 的矩阵相关 | 2462 | -0.10158499415134617 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_d2df3a0c0ae73f6187f966d1` | jp/JP13 | raw_count / raw_count 与 lift 的矩阵相关 | 1700 | -0.17518818290206703 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_40b0d0000e0c83a46ffa0715` | jp/JP13 | raw_count / raw_count 与 lift 的矩阵相关 | 1700 | -0.11399901471328458 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_05db8fc4595060fe14850271` | jp/JP13 | raw_count / raw_count 与 lift 的矩阵相关 | 2445 | -0.11586322722569517 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_66334b1f54f2dc399b426c39` | jp/JP13 | raw_count / raw_count 与 lift 的矩阵相关 | 2445 | -0.11593585207281354 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_7a9bf04f8eb67be6fc691a2c` | jp/JP14 | raw_count / raw_count 与 lift 的矩阵相关 | 1879 | -0.27273836046389727 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_268c8f629547886f1eefc0e9` | jp/JP14 | raw_count / raw_count 与 lift 的矩阵相关 | 1879 | -0.08733245914839537 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_64a8a9e23f907bb4651e8d8c` | jp/JP14 | raw_count / raw_count 与 lift 的矩阵相关 | 5719 | -0.4942056936280534 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_6641377ca9fb0073fcf1cd4c` | jp/JP14 | raw_count / raw_count 与 lift 的矩阵相关 | 5719 | -0.04586048670115877 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_bd22d05accfc5af6cb51cafc` | jp/JP15 | raw_count / raw_count 与 lift 的矩阵相关 | 1883 | -0.2791760041223691 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_b1352cc8cf744cda4d616172` | jp/JP15 | raw_count / raw_count 与 lift 的矩阵相关 | 1883 | -0.06025664448214036 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_b980c06c1536921060e042dc` | jp/JP15 | raw_count / raw_count 与 lift 的矩阵相关 | 5805 | -0.5260202038765549 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_5c84dceb8117e2f6c8cf8865` | jp/JP15 | raw_count / raw_count 与 lift 的矩阵相关 | 5805 | -0.05346094209613276 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_8e23d921123ab3c5cc0d474c` | jp/JP16 | raw_count / raw_count 与 lift 的矩阵相关 | 2017 | -0.3448958360080986 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_a617ab7a6a42c42fa7098de6` | jp/JP16 | raw_count / raw_count 与 lift 的矩阵相关 | 2017 | -0.07890599620938923 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_3a089adfbe18e9b03524b182` | jp/JP16 | raw_count / raw_count 与 lift 的矩阵相关 | 5890 | -0.5358380982568266 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_649fe65fde5143f483c64a82` | jp/JP16 | raw_count / raw_count 与 lift 的矩阵相关 | 5890 | -0.06638332874022139 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_9cfddd95ecf5e359e6936cb6` | jp/JP17 | raw_count / raw_count 与 lift 的矩阵相关 | 2144 | -0.2627895092511842 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_88fa8f65c449c080d60abbff` | jp/JP17 | raw_count / raw_count 与 lift 的矩阵相关 | 2144 | -0.04232673010377398 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_37ccb57b4d0ab9a7ea00776c` | jp/JP17 | raw_count / raw_count 与 lift 的矩阵相关 | 6246 | -0.44638241474131557 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_efa794f8a485bd21a8a93b7e` | jp/JP17 | raw_count / raw_count 与 lift 的矩阵相关 | 6246 | -0.043171376140990765 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_f966bed43abc7b0b39c28d2c` | jp/JP18 | raw_count / raw_count 与 lift 的矩阵相关 | 2202 | -0.21933887425164406 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_d7e79e11aa4a530a8d8e97fc` | jp/JP18 | raw_count / raw_count 与 lift 的矩阵相关 | 2202 | -0.0558758026986177 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_dd1808dc7192ec59594c2cd1` | jp/JP18 | raw_count / raw_count 与 lift 的矩阵相关 | 6425 | -0.41948624399239387 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_093af9e2c90f2cf9cb503683` | jp/JP18 | raw_count / raw_count 与 lift 的矩阵相关 | 6425 | -0.030186278545809592 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_ed705b0835f07ddd86f5d659` | jp/JP19 | raw_count / raw_count 与 lift 的矩阵相关 | 2250 | -0.24304196962330885 | 1.0 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_142b824bb21d32d91a385942` | jp/JP19 | raw_count / raw_count 与 lift 的矩阵相关 | 2250 | -0.08483967932405675 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_1e2783f7b02238e8d261620c` | jp/JP19 | raw_count / raw_count 与 lift 的矩阵相关 | 6433 | -0.44561995365745505 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_a8d6933aacb6650edabcef30` | jp/JP19 | raw_count / raw_count 与 lift 的矩阵相关 | 6433 | -0.028637389271512118 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_a5fd61563c98b5173e709bc7` | jp/JP20 | raw_count / raw_count 与 lift 的矩阵相关 | 2331 | -0.21409504485982803 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_923d25449f82b132b19d0a43` | jp/JP20 | raw_count / raw_count 与 lift 的矩阵相关 | 2331 | -0.06369866261975576 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_ff82dcb14bc23a706f48bcfb` | jp/JP20 | raw_count / raw_count 与 lift 的矩阵相关 | 6545 | -0.39566091652521357 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_09b491ce19e840c16bb532cf` | jp/JP20 | raw_count / raw_count 与 lift 的矩阵相关 | 6545 | -0.023387545816579335 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_cf0f77284228b636be5fa7e1` | jp/JP21 | raw_count / raw_count 与 lift 的矩阵相关 | 2345 | -0.20934567474147955 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_a9276fb768e51a8a30cfd747` | jp/JP21 | raw_count / raw_count 与 lift 的矩阵相关 | 2345 | -0.04508540602064743 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_e1eed1c7555e79fc1b4422b5` | jp/JP21 | raw_count / raw_count 与 lift 的矩阵相关 | 6617 | -0.3803966199665616 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_fc85b33a52e8d16fd33f2ad0` | jp/JP21 | raw_count / raw_count 与 lift 的矩阵相关 | 6617 | -0.02814286917026676 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_7449b68e49f8113ba16d9264` | jp/JP22 | raw_count / raw_count 与 lift 的矩阵相关 | 2399 | -0.20153143910503676 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_df70544239dee6cdc4dc7440` | jp/JP22 | raw_count / raw_count 与 lift 的矩阵相关 | 2399 | -0.03757791905592665 | 0.6666666666666666 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_9859014375ac3ce0bbe0525f` | jp/JP22 | raw_count / raw_count 与 lift 的矩阵相关 | 6721 | -0.3834946683998861 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_18762c73a2728fa3b93e0d1d` | jp/JP22 | raw_count / raw_count 与 lift 的矩阵相关 | 6721 | -0.04197731346681527 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_1e7fb24428ea8ee74d163194` | jp/JP22_VS_JP21 | lift / lift 与 lift 的矩阵相关 | 1756 | 0.9564757516979145 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_7ef624a4351963465a4582d9` | jp/JP22_VS_JP21 | lift / lift 与 lift 的矩阵相关 | 1756 | 0.9057524079472563 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_9e59dcb0f3092d8c108d5512` | jp/JP22_VS_JP21 | raw_count / raw_count 与 raw_count 的矩阵相关 | 1712 | 0.9888379924248578 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_fc11a5b6f8672630247b30ca` | jp/JP22_VS_JP21 | raw_count / raw_count 与 raw_count 的矩阵相关 | 1712 | 0.9967026213454588 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_21b1eeaffc666dbcda7d587c` | jp/JP22_VS_JP21 | lift / lift 与 lift 的矩阵相关 | 3562 | 0.9688767061084879 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_28050cb7365bebf8ac033332` | jp/JP22_VS_JP21 | lift / lift 与 lift 的矩阵相关 | 3562 | 0.873574467565118 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_f9c3dd4495d1869fbb4cdb22` | jp/JP22_VS_JP21 | raw_count / raw_count 与 raw_count 的矩阵相关 | 3562 | 0.9861642706282484 | 0.3333333333333333 | — | not_applied | tested |
| `matrix_correlations.csv` | `ni_ffa375e7cbb7fa6303b86cbb` | jp/JP22_VS_JP21 | raw_count / raw_count 与 raw_count 的矩阵相关 | 3562 | 0.9975038051122758 | 0.3333333333333333 | — | not_applied | tested |
| `mrqap_coefficients.csv` | `ni_9ec5bacbac34490be9ae39c9` | cn/CN10 | cosine / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_35c6523433746afae6c1e6e0` | cn/CN10 | cosine / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_d04de4ccc44e0fb30c7a05e1` | cn/CN10 | cosine / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_41af226f2b6b5558a62b80d0` | cn/CN10 | cosine / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_e9b844e72545d918792c335e` | cn/CN10 | cosine / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_0349f92308f10692f4d6eaec` | cn/CN10 | cosine / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_2009ca84ffdbc0164f300109` | cn/CN10 | cosine / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_70c81a95cba69c92cbe20c11` | cn/CN10 | cosine / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_b57ab45567f6f2e9b7a9b77e` | cn/CN10 | cosine / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_c83a2e6b3495473434c7c3b6` | cn/CN10 | cosine / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_ac69ae989038a60c8bd6f071` | cn/CN10 | cosine / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_485d43e70e8c7efeca253535` | cn/CN10 | cosine / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_39b28142a6d25a8967de3238` | cn/CN10 | cosine / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_302874a75beeb5141710b15c` | cn/CN10 | cosine / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_298d434eca4428829cce78b3` | cn/CN10 | formed / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_306294c0554a4d5dcd485b7b` | cn/CN10 | formed / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_563d6244f4d1d8755edd255c` | cn/CN10 | formed / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_94a5d3b767ed195c811d3ee7` | cn/CN10 | formed / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_3157333138d742e311a126fe` | cn/CN10 | formed / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_9138245c9eaaf0d86adbfda9` | cn/CN10 | formed / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_28f183b3dae7a80d4db8bacb` | cn/CN10 | formed / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_8b072c89f03468e6a252d423` | cn/CN10 | formed / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_644aad737d43c45d2ac05f4e` | cn/CN10 | formed / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_539a0597cec067b1845c36dc` | cn/CN10 | formed / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_fadae3ddeea671c7eef64d34` | cn/CN10 | formed / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_4aa0b289c32e1cac33803382` | cn/CN10 | formed / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_2edd91b2cb6c4802d9c38e36` | cn/CN10 | formed / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_a81363b2b1bfd96d01208691` | cn/CN10 | formed / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_a1700cdd591bce49a8f11ff0` | cn/CN10 | lift / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_5ed459abb6c37135e9c5bbcb` | cn/CN10 | lift / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_955b1be93a1b8b5a050d3e1d` | cn/CN10 | lift / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_9140250fe693699f7eafcea3` | cn/CN10 | lift / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_e462b4640a386186287e0f04` | cn/CN10 | lift / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_55709cb1cbe009115ae39632` | cn/CN10 | lift / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_175c5706e3aba1815bbbbadb` | cn/CN10 | lift / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_2ed1ec76ba0bc38b63adae21` | cn/CN10 | lift / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_78976af64941f6c08fb509a2` | cn/CN10 | lift / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_c3006ca85bc81125d89a7194` | cn/CN10 | lift / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_34e88cc2018239776df86d6f` | cn/CN10 | lift / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_80d52df21c24a9698ee8d631` | cn/CN10 | lift / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_1652299ee8dbab5118127632` | cn/CN10 | lift / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_6fd6c4278b56a411fa104cd5` | cn/CN10 | lift / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_2756b86be8b6f04d423ab97f` | cn/CN10 | phi / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_54538eded058817fc5753391` | cn/CN10 | phi / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_0cbbe583a5c2aac889ee3e7b` | cn/CN10 | phi / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_f1c261d407eeddd989f82e20` | cn/CN10 | phi / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_f941d3fe43739eda05e6a95b` | cn/CN10 | phi / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_96abf9bd0bad91b2dd8ff608` | cn/CN10 | phi / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_6b735b48e9bf2fd689eafeab` | cn/CN10 | phi / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_15cd8c0e5138139fbcb0e9c1` | cn/CN10 | phi / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_ca865e3a2c046f3194a2696c` | cn/CN10 | phi / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_8a1b7f20226437a6e1fa1228` | cn/CN10 | phi / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_8f2a0735d7d46793693474cc` | cn/CN10 | phi / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_4a7ea41ab4d91af83df0bd56` | cn/CN10 | phi / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_0e0e56ef9f20f59576e6e2e4` | cn/CN10 | phi / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_10858ae918ef28dc311fa069` | cn/CN10 | phi / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_ab39032219108bd2faba615f` | cn/CN11 | cosine / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_3e0f9e9d75955b8e9ded711b` | cn/CN11 | cosine / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_3156c6869cb1b4a6cb9892c0` | cn/CN11 | cosine / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_f8d7ac737b90e56c6636d6f3` | cn/CN11 | cosine / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_5d14a28612df4d25bc8d7231` | cn/CN11 | cosine / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_790bede6824ae145e532870f` | cn/CN11 | cosine / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_53dfab499b2606125f8124a2` | cn/CN11 | cosine / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_61ce41efc5fa2d42c8f297d3` | cn/CN11 | cosine / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_4cd2a761623de951d4330293` | cn/CN11 | cosine / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_2ddf86290e949c16d13908f8` | cn/CN11 | cosine / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_b592e368652923e8742af1d2` | cn/CN11 | cosine / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_7da560ea3518d52d4e141810` | cn/CN11 | cosine / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_b0f306d3c2ad2ba4b261dd0a` | cn/CN11 | cosine / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_f185ebfc9c00f5ac03ba7b94` | cn/CN11 | cosine / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_c887c1b49dc7146d796dc12e` | cn/CN11 | formed / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_80edaf45b9be6dc2d146dfac` | cn/CN11 | formed / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_8868e3b9fd6f792f5f530206` | cn/CN11 | formed / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_01c43f907a4541afaaa0e250` | cn/CN11 | formed / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_d48551fc2dd5a65a0a6a274d` | cn/CN11 | formed / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_bc364f1fdcec83a670df0b3b` | cn/CN11 | formed / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_6521235bd1875683b4a609a0` | cn/CN11 | formed / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_fd2278feeebeb5e13dfdf070` | cn/CN11 | formed / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_bb0917003fcc6949f4f4e7ea` | cn/CN11 | formed / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_20c120e87b4e00e4f272d6b5` | cn/CN11 | formed / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_7ce4d634db912c5f7b477c4c` | cn/CN11 | formed / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_bc62e7c6e5895453cc4c71c5` | cn/CN11 | formed / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_f1026a0bf7ddbbe99c2517f2` | cn/CN11 | formed / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_0916cde37c6d52e34fa9f215` | cn/CN11 | formed / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_8af7e7cba38ab237f6738548` | cn/CN11 | lift / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_009e665938fb1181393d92ce` | cn/CN11 | lift / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_e584db8015db370ce1fa30ca` | cn/CN11 | lift / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_94d1157198bfbae1c61f8ae2` | cn/CN11 | lift / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_18c4b504dc199fe00a5b5ddf` | cn/CN11 | lift / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_c0bfc267e94c480ee846e51f` | cn/CN11 | lift / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_1ba74a7756ce0c325fd8d9de` | cn/CN11 | lift / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_14575e6055601444afffc99d` | cn/CN11 | lift / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_4c9e9415ed05b4dff9becf14` | cn/CN11 | lift / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_87d1b211ef9ace0f9a3706dc` | cn/CN11 | lift / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_5b9a9b75a340d7af1391fae3` | cn/CN11 | lift / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_b209bd8f034e7bd6d7408e34` | cn/CN11 | lift / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_1d9c35218ca9263143d0f510` | cn/CN11 | lift / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_1e878f0a3b9bf031f955b5f2` | cn/CN11 | lift / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_381e73a1904ef2e422dd216f` | cn/CN11 | phi / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_39e5bf55388683e9614af102` | cn/CN11 | phi / 端点 A 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_c5df3becb80b23edf76a0273` | cn/CN11 | phi / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_80286f6ad3e3f8e6627998a4` | cn/CN11 | phi / 端点 B 选择人数对数 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_35858dd86a1279bdc714e090` | cn/CN11 | phi / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_c3b3ac9d8bc37257ed8225bd` | cn/CN11 | phi / 社群有交集 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_ac8c6fe07026d493c9aeeabc` | cn/CN11 | phi / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_14e2fff5a5f1877f1fe9cca2` | cn/CN11 | phi / 区域相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_acd4a0f98a16a0db8a10160b` | cn/CN11 | phi / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_ce54f27eeb38cef656abde56` | cn/CN11 | phi / 关卡相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_db5e070c9864a18fc1ec9bf8` | cn/CN11 | phi / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_a5c408104384a69f4451db40` | cn/CN11 | phi / 首次作品相同 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_0e23eca33c5b461fd0f73087` | cn/CN11 | phi / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |
| `mrqap_coefficients.csv` | `ni_e2f736142aa9f4c1a2d13f8d` | cn/CN11 | phi / 同作品相邻关卡 | 0 | — | — | — | not_applied | not_estimable |

## 覆盖与警告

- `hypothesis_tests.csv`：280 行；152 行无法估计。
- `matrix_correlations.csv`：98 行；0 行无法估计。
- `mrqap_coefficients.csv`：112 行；112 行无法估计。
- `sensitivity_scan.csv`：0 行；0 行无法估计。
- 尚未提供敏感性扫描结果；`sensitivity_scan.csv` 仅有表头，不能视为稳健性证据。
- 共同投票不等于 CP 或原作关系。
- 空白不等于真实 0。
- 显著性不等于因果关系。
- 不同届次和地区的投票规则可能不同。
- 部分同投数据为公开关联列表而非完整矩阵。

## 溯源

- 输入及输出的 SHA-256、版本、参数和缺失记录：`model_run_manifest.json`。
- 字段契约：`metadata/network_inference_output.schema.json`。
- `figures/` 为可选展示，不包含独占数值。
