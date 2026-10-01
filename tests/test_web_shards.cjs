const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { createLoader } = require('../vote_explorer_web/shards.js');

test('scope requests, two-entry cache, integrity failure and retry', async () => {
  const body = JSON.stringify({ defaults: { blank: '', seed: '8509473029546610632' }, columns: ['value'], values: [['0']] });
  const bytes = Buffer.from(body);
  const entry = {path: 'part.json', bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex')};
  const keys = ['CN10','CN11','JP22'].map(r => ['covote_pairs',r,'character']);
  const entries = Object.fromEntries(keys.map(k => [JSON.stringify(k),[entry]]));
  let calls = [], corrupt = false;
  const fetcher = async url => { calls.push(url); return new Response(url.endsWith('index.json') ? JSON.stringify({entries}) : corrupt ? body.replace('0','1') : body); };
  const loader = createLoader('/tables/', fetcher);
  const rows = await loader.load(keys[0]);
  assert.deepEqual(rows, [{blank:'',seed:'8509473029546610632',value:'0'}]);
  await loader.load(keys[0]); assert.equal(calls.length,2);
  await loader.load(keys[1]); await loader.load(keys[2]); assert.equal(loader.cacheSize(),2);
  assert.deepEqual(await loader.load(['covote_pairs','CN1','character']),[]);
  loader.clear(); corrupt=true;
  await assert.rejects(loader.load(keys[0]), /SHA-256/);
  corrupt=false; await loader.load(keys[0]);
  assert.ok(calls.every(u=>u.startsWith('/tables/')));
});
