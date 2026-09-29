/* Read-only presentation of build-time results. No estimators or raw matrices. */
(function (root) {
  'use strict';
  const SCOPE_LABELS = { character: '角色', music: '音乐', cross_department: '角色 × 音乐' };
  const LABELS = {
    intersection_count: '共同投票人数', conditional_rate: '条件同投率', lift: '集中倍数',
    cosine: '余弦相似度', ochiai: 'Ochiai', jaccard: 'Jaccard', phi: 'φ', pmi: 'PMI', npmi: 'NPMI',
    cp_vote_count: 'CP 官方票数', weighted_degree: '加权度', unweighted_degree: '度', pagerank: 'PageRank',
    betweenness: '介数中心性', k_core: 'k-core', bridge_score: '桥接分数', node_count: '节点数',
    edge_count: '边数', internal_weight: '社区内部权重', modularity_contribution: '模块度贡献',
    modularity: '模块度', degree_assortativity: '度同配性', nmi_vs_connected_components: '相对连通分量 NMI',
    community_count: '社区数', connected_component_count: '连通分量数',
    same_first_appearance_work: '首次作品相同', same_work: '首次作品相同', same_stage: '关卡相同',
    same_work_adjacent_stage: '同作相邻关卡', same_community: '社群有交集', same_region: '区域相同',
    same_character_type: '角色类型相同', same_source_group: '来源组相同',
    log_count_a: '端点 A 人数对数', log_count_b: '端点 B 人数对数', intercept: '截距',
    complete_matrix: '完整矩阵', exact_complete_2x2: '完整四格矩阵', observed: '仅已观测关系',
    common_observed_pairs_only: '仅共同观测配对（非完整矩阵）', model_complete_cases_only: '模型完整案例子集',
    partial_observed_pairs: '部分公开配对', published_leading_list: '公开前列（列表外未知）',
    cross_department_conditional_only: '跨部门条件口径', not_reported: '未报告 / 未知',
    not_applicable: '不适用', not_applied: '未校正', no_complete_cases: '无完整案例，无法估计',
    metric_unavailable: '指标不可用', both_groups_empty_or_unknown: '两组为空或未知',
    exploratory: '探索性', exploratory_sensitivity: '探索性阈值扫描',
  };
  const COMMUNITY_METRICS = {
    community_summary: ['node_count', 'edge_count', 'internal_weight', 'modularity_contribution'],
    community_assignments: ['weighted_degree', 'unweighted_degree', 'pagerank', 'betweenness', 'k_core', 'bridge_score'],
    node_centrality: ['weighted_degree', 'unweighted_degree', 'pagerank', 'betweenness', 'k_core', 'bridge_score'],
    modularity_summary: ['modularity', 'degree_assortativity', 'nmi_vs_connected_components', 'node_count', 'edge_count', 'community_count', 'connected_component_count'],
  };
  const label = value => LABELS[value] || String(value ?? '');
  const pick = (row, ...keys) => keys.map(k => row[k]).find(v => v !== undefined && v !== null && v !== '') ?? '';
  function numeric(value) {
    if (value === null || value === undefined || String(value).trim() === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  function decode(payload) {
    if (payload.schema_version !== 1 || !Array.isArray(payload.columns) || !Array.isArray(payload.values) || payload.row_count !== payload.values.length) throw new Error('研究结果格式不兼容，请重新构建');
    const rows = payload.values.map(values => {
      if (values.length !== payload.columns.length) throw new Error('研究结果列数不匹配');
      return { ...payload.defaults, ...Object.fromEntries(payload.columns.map((key, i) => [key, values[i]])) };
    });
    return { ...payload, rows };
  }
  function createLoader(base, fetcher = root.fetch.bind(root)) {
    const cache = new Map();
    let indexPromise;
    async function json(path) {
      const response = await fetcher(new URL(path, base).href);
      if (!response.ok) throw new Error(`研究结果读取失败：${path}（${response.status}）`);
      return response.json();
    }
    return {
      index() {
        if (!indexPromise) indexPromise = json('index.json').then(index => {
          if (index.schema_version !== 1 || !Array.isArray(index.entries)) throw new Error('研究索引格式不兼容');
          return index;
        }).catch(error => { indexPromise = null; throw error; });
        return indexPromise;
      },
      shard(entry) {
        const path = entry.path;
        if (!/^[a-zA-Z0-9_.→-]+[.]json$/u.test(path) || path.includes('..')) return Promise.reject(new Error('无效研究结果路径'));
        if (cache.has(path)) { const value = cache.get(path); cache.delete(path); cache.set(path, value); return value; }
        const promise = json(path).then(decode).catch(error => { cache.delete(path); throw error; });
        cache.set(path, promise);
        while (cache.size > 3) cache.delete(cache.keys().next().value);
        return promise;
      },
    };
  }
  function filterRows(rows, filters) {
    const minPairs = Math.max(0, numeric(filters.minPairs) ?? 0);
    const search = String(filters.search || '').trim().toLocaleLowerCase();
    return rows.filter(row => {
      if (filters.completeOnly && row.web_complete_matrix !== true) return false;
      if (!filters.showExploratory && row.web_exploratory === true) return false;
      if (minPairs > 0 && (numeric(row.web_n_pairs) === null || numeric(row.web_n_pairs) < minPairs)) return false;
      for (const [key, column] of [['method', 'web_method'], ['threshold', 'web_threshold'], ['algorithm', 'web_algorithm']]) {
        if (filters[key] && row[column] !== filters[key]) return false;
      }
      if (!COMMUNITY_METRICS[filters.level] && filters.metric && row.web_metric !== filters.metric) return false;
      return !search || Object.values(row).some(v => String(v ?? '').toLocaleLowerCase().includes(search));
    });
  }
  function effect(row, level, metric) {
    if (COMMUNITY_METRICS[level]) return numeric(row[metric]);
    if (level === 'coverage') return null;
    const field = { hypothesis_tests: 'cliffs_delta', matrix_correlations: 'observed_correlation', mrqap_coefficients: 'coefficient', sensitivity_scan: 'effect_size' }[level];
    return numeric(pick(row, field, 'effect_size'));
  }
  function feature(row, level) {
    if (level === 'matrix_correlations') return `${row.matrix_a} ${row.metric_a} × ${row.matrix_b} ${row.metric_b} · ${row.correlation_method}`;
    if (level === 'modularity_summary') return `${row.web_round} · ${SCOPE_LABELS[row.web_scope] || row.web_scope}`;
    if (level === 'coverage') return row.analysis || '';
    return pick(row, 'name_cn', 'name_jp', 'canonical_name', 'feature_label_zh') || label(pick(row, 'feature_id', 'hypothesis', 'predictor', 'community_id'));
  }
  function probability(row, level) {
    // Ordinary regression p is deliberately never a replacement for QAP p.
    return level === 'mrqap_coefficients' ? pick(row, 'qap_p', 'p_value') : pick(row, 'permutation_p', 'raw_p', 'p_value');
  }
  function table(rows, level, metric) {
    const community = Boolean(COMMUNITY_METRICS[level]);
    const effectTitle = community ? label(metric) : level === 'mrqap_coefficients' ? '回归系数' : level === 'matrix_correlations' ? '相关系数' : 'Cliff’s δ';
    const headers = ['项目 / 节点', ...(level === 'coverage' ? ['可用结果行数'] : [effectTitle]),
      '置换 p', '校正后 p', '校正方法', '配对数', '配对数口径', '状态', '完整性', '删失状态',
      '探索性', '统计方法', '指标 / 权重', '阈值', '社区', '请求 / 有效置换', '随机种子', '警告', '来源'];
    const values = rows.map(row => [feature(row, level), level === 'coverage' ? row.result_rows : effect(row, level, metric) ?? '',
      probability(row, level), pick(row, 'adjusted_p', 'q_value'), pick(row, 'adjustment_method', 'web_adjustment') || '未报告',
      row.web_n_pairs, row.web_pair_basis, label(pick(row, 'status', 'source_status', 'data_status')) || '未报告',
      label(row.web_completeness), label(row.web_censoring), row.web_exploratory ? '是（探索性）' : '源结果未标记',
      row.web_method, row.web_metric, label(row.web_threshold), row.community_id || '',
      `${row.web_permutations === '' ? '未报告' : row.web_permutations} / ${pick(row, 'valid_permutations', 'permutations_used') || '未报告'}`,
      row.web_random_seed === '' ? '未报告' : row.web_random_seed, pick(row, 'web_warning', 'warning', 'reason'), row.web_source_path]);
    return { headers, values, effectTitle };
  }
  function csv(rows) {
    // Preserve every source column and unrounded value, including blanks/seeds.
    const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
    const quote = String.fromCharCode(34);
    const cell = value => quote + String(value ?? '').replaceAll(quote, quote + quote) + quote;
    return [columns, ...rows.map(row => columns.map(k => row[k]))].map(row => row.map(cell).join(',')).join(String.fromCharCode(13, 10));
  }
  const api = { SCOPE_LABELS, COMMUNITY_METRICS, label, pick, numeric, decode, createLoader, filterRows, effect, feature, probability, table, csv };
  root.VoteResearch = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
