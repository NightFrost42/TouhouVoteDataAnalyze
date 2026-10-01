/* Bounded, verified lazy loading. Never fall back to a full matrix download. */
(function (root) {
  function createLoader(base, fetcher = fetch) {
    let indexPromise;
    const cache = new Map();
    async function verified(entry) {
      const response = await fetcher(base + entry.path);
      if (!response.ok) throw new Error(`读取分片失败（HTTP ${response.status}）`);
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength !== entry.bytes) throw new Error('分片大小不匹配');
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('');
      if (hash !== entry.sha256) throw new Error('分片 SHA-256 不匹配');
      if (entry.path.endsWith('.gz')) {
        const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
        return JSON.parse(await new Response(stream).text());
      }
      return JSON.parse(new TextDecoder().decode(bytes));
    }
    function index() {
      if (!indexPromise) indexPromise = fetcher(base + 'index.json').then(r => {
        if (!r.ok) throw new Error(`读取分片索引失败（HTTP ${r.status}）`);
        return r.json();
      }).catch(e => { indexPromise = null; throw e; });
      return indexPromise;
    }
    function load(selection) {
      const key = JSON.stringify(selection);
      if (cache.has(key)) {
        const value = cache.get(key); cache.delete(key); cache.set(key, value); return value;
      }
      const promise = (async () => {
        const manifest = await index();
        const entries = manifest.entries[key] || [];
        const rows = [];
        // Decode one bounded shard at a time; retain only the selected dataset.
        for (const entry of entries) {
          const payload = await verified(entry);
          for (const values of payload.values) {
            if (values.length !== payload.columns.length) throw new Error('分片列数不匹配');
            const row = { ...payload.defaults };
            payload.columns.forEach((name, i) => { row[name] = values[i]; });
            rows.push(row);
          }
        }
        return rows;
      })();
      cache.set(key, promise);
      while (cache.size > 2) cache.delete(cache.keys().next().value);
      promise.catch(() => { if (cache.get(key) === promise) cache.delete(key); });
      return promise;
    }
    return { load, verified, clear: () => cache.clear(), cacheSize: () => cache.size };
  }
  root.TableShards = { createLoader };
  if (typeof module !== 'undefined') module.exports = root.TableShards;
})(globalThis);
