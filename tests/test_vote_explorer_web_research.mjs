import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const research = require('../vote_explorer_web/research.js');
const rows = [
  { id: 'zero', web_metric: 'phi', web_complete_matrix: true, web_exploratory: false, web_n_pairs: '12', web_method: 'qap', web_threshold: 'count ≥ 100', web_algorithm: 'louvain', coefficient: '0', qap_p: '0', permutation_seed: '8509473029546610632' },
  { id: 'missing', web_metric: 'phi', web_complete_matrix: false, web_exploratory: false, web_n_pairs: '', coefficient: '', qap_p: '', ordinary_p: '.001' },
  { id: 'exploration', web_metric: 'phi', web_complete_matrix: true, web_exploratory: true, web_n_pairs: '20', coefficient: '-.5' },
];
test('blank effects and unknown pair counts never become observed zero', () => {
  assert.equal(research.effect(rows[0], 'mrqap_coefficients', 'phi'), 0);
  assert.equal(research.effect(rows[1], 'mrqap_coefficients', 'phi'), null);
  assert.equal(research.probability(rows[1], 'mrqap_coefficients'), '');
  assert.equal(research.numeric('NA'), null);
  assert.equal(research.numeric(''), null);
  assert.equal(research.numeric('0'), 0);
});
test('completeness, exploratory, minimum pairs and scenario filters are independent', () => {
  const filter = overrides => research.filterRows(rows, { level: 'mrqap_coefficients', ...overrides }).map(r => r.id);
  assert.deepEqual(filter({}), ['zero', 'missing']);
  assert.deepEqual(filter({ completeOnly: true }), ['zero']);
  assert.deepEqual(filter({ minPairs: 1 }), ['zero']);
  assert.deepEqual(filter({ showExploratory: true, minPairs: 15 }), ['exploration']);
  assert.deepEqual(filter({ method: 'qap', threshold: 'count ≥ 100', algorithm: 'louvain' }), ['zero']);
  assert.deepEqual(filter({ threshold: 'not_run' }), []);
  assert.deepEqual(filter({ search: 'MISSING' }), ['missing']);
});
test('CSV retains blank cells, zero p, original precision and long seeds', () => {
  const csv = research.csv(rows);
  assert.ok(csv.includes('8509473029546610632'));
  assert.ok(csv.includes('.001'));
  assert.ok(csv.includes(String.fromCharCode(13, 10)));
  assert.ok(research.csv([{ name: 'a,b', note: 'a' + String.fromCharCode(34) + 'b' }]).includes('a' + String.fromCharCode(34, 34) + 'b'));
});
test('compact decoder preserves types and rejects inconsistent data', () => {
  const payload = { schema_version: 1, defaults: { complete: false }, columns: ['effect', 'seed'], values: [['', '8509473029546610632'], ['0', '42']], row_count: 2 };
  assert.deepEqual(research.decode(payload).rows, [{ complete: false, effect: '', seed: '8509473029546610632' }, { complete: false, effect: '0', seed: '42' }]);
  assert.throws(() => research.decode({ ...payload, row_count: 3 }));
  assert.throws(() => research.decode({ ...payload, columns: ['effect'] }));
});
test('loader requests only index and selected shard, retries errors, bounds cache', async () => {
  const calls = []; let fail = true;
  const loader = research.createLoader('https://local.test/web_data/research/', async url => {
    calls.push(url);
    if (url.endsWith('index.json')) return { ok: true, json: async () => ({ schema_version: 1, entries: [] }) };
    if (fail) { fail = false; return { ok: false, status: 503 }; }
    return { ok: true, json: async () => ({ schema_version: 1, columns: [], values: [[]], defaults: { effect: '' }, row_count: 1 }) };
  });
  assert.equal(calls.length, 0);
  await loader.index(); await loader.index(); assert.equal(calls.length, 1);
  await assert.rejects(loader.shard({ path: 'selected.json' }));
  await loader.shard({ path: 'selected.json' }); await loader.shard({ path: 'selected.json' });
  assert.equal(calls.length, 3);
  for (const path of ['a.json', 'b.json', 'c.json']) await loader.shard({ path });
  await loader.shard({ path: 'selected.json' }); assert.equal(calls.length, 7);
  await assert.rejects(loader.shard({ path: '../raw_matrix.json' }));
  assert.ok(calls.every(url => url.includes('/web_data/research/')));
});
test('deployed data covers all rounds/scopes and preserves unavailable estimates', () => {
  const base = new URL('../vote_explorer_web/web_data/research/', import.meta.url);
  const index = JSON.parse(readFileSync(new URL('index.json', base), 'utf8'));
  const rounds = [...Array.from({ length: 11 }, (_, i) => `CN${i + 1}`), ...Array.from({ length: 20 }, (_, i) => `JP${i + 3}`)];
  for (const round of rounds) for (const scope of ['character', 'music', 'cross_department']) {
    assert.ok(index.entries.some(e => e.level === 'community_summary' && e.round === round && e.scope === scope), `${round}/${scope}`);
  }
  assert.ok(index.entries.every(e => e.size_bytes < 300000), 'result shards remain small on mobile');
  const entry = index.entries.find(e => e.level === 'mrqap_coefficients' && e.round === 'CN11');
  const data = research.decode(JSON.parse(readFileSync(new URL(entry.path, base), 'utf8')));
  assert.ok(data.rows.some(r => r.status === 'no_complete_cases' && research.effect(r, 'mrqap_coefficients') === null));
});
