/* Fixed browser assertions. Run with Playwright; BROWSER_CHANNEL is optional. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(__dirname, '.tmp-web-research');
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((request, response) => {
  const file = path.resolve(root, '.' + decodeURIComponent(new URL(request.url, 'http://localhost').pathname));
  if (!file.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
  const target = file.endsWith('vote_explorer_web') ? path.join(file, 'index.html') : file;
  const ext = path.extname(target);
  response.setHeader('Content-Type', { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.css': 'text/css; charset=utf-8' }[ext] || 'text/plain; charset=utf-8');
  const stream = fs.createReadStream(target);
  stream.on('error', () => response.writeHead(404).end());
  stream.pipe(response);
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push(request.url()));
  const base = `http://127.0.0.1:${server.address().port}/vote_explorer_web/`;
  const ready = async () => {
    await page.waitForFunction(() => document.getElementById('loading-state').classList.contains('hidden'));
    assert.ok(!(await page.locator('#status-line').getAttribute('class')).includes('error-text'), await page.locator('#status-line').innerText());
  };
  const choose = async (id, value) => { await page.selectOption('#' + id, value); await ready(); };
  try {
    await page.goto(base, { waitUntil: 'networkidle' }); await ready();
    assert.ok(await page.locator('#result-table tbody tr').count() > 0);
    assert.ok(!requests.some(url => /templates[.]json|research.*index[.]json|analysis_covote_pairs/.test(url)), 'homepage is lazy');
    await choose('analysis-kind', 'research');
    assert.ok(await page.locator('#result-table tbody tr').count() > 0);
    assert.match(await page.locator('#research-caveat').innerText(), /完整性.*删失.*随机种子/);
    await page.locator('#research-provenance summary').click();
    assert.match(await page.locator('#research-run-details').innerText(), /sha256/);
    await page.locator('#research-provenance summary').click();
    await choose('research-complete', 'complete');
    assert.equal(await page.locator('#result-table tbody tr').count(), 0);
    await choose('research-complete', 'all');
    await choose('research-comparison', 'CN11_vs_CN10');
    assert.match(await page.locator('#chart-title').innerText(), /CN11 与 CN10/);
    await choose('research-level', 'mrqap_coefficients');
    assert.ok(await page.locator('#result-table tbody tr').count() > 0);
    assert.equal(await page.locator('#chart circle').count(), 0, 'unestimated coefficients are not plotted as zero');
    assert.match(await page.locator('#result-table tbody').innerText(), /无法估计|指标不可用/);
    await choose('research-level', 'hypothesis_tests');
    assert.equal(await page.locator('#result-table tbody tr').count(), 0, 'exploratory results hidden by default');
    await choose('research-exploratory', 'show');
    assert.ok(await page.locator('#result-table tbody tr').count() > 0);
    await choose('research-level', 'sensitivity_scan');
    assert.match(await page.locator('#research-caveat').innerText(), /无运行清单/);
    await page.fill('#research-min-pairs', '999999');
    await page.waitForFunction(() => document.querySelectorAll('#result-table tbody tr').length === 0);
    await page.fill('#research-min-pairs', '0');
    await page.waitForFunction(() => document.querySelectorAll('#result-table tbody tr').length > 0);
    await choose('research-level', 'community_assignments');
    await page.fill('#top-n', '10');
    await page.waitForFunction(() => document.querySelectorAll('#result-table tbody tr').length === 10);
    let downloadPromise = page.waitForEvent('download');
    await page.click('#download-button');
    let download = await downloadPromise;
    const current = fs.readFileSync(await download.path(), 'utf8');
    assert.equal(await page.evaluate(text => parseCSV(text).length, current), 10);
    assert.ok(current.includes('web_completeness'));
    downloadPromise = page.waitForEvent('download');
    await page.click('#research-download-all'); download = await downloadPromise;
    const all = fs.readFileSync(await download.path(), 'utf8');
    assert.ok(await page.evaluate(text => parseCSV(text).length, all) > 10);
    await choose('research-level', 'node_centrality');
    await choose('research-metric', 'pagerank');
    assert.match(await page.locator('#result-table thead').innerText(), /PageRank/);
    await choose('research-scope', 'music');
    await choose('round', 'JP22');
    await choose('research-level', 'community_summary');
    await page.screenshot({ path: path.join(output, 'research-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await choose('research-scope', 'cross_department');
    assert.equal(await page.locator('#research-controls').isVisible(), true);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'mobile layout stays within viewport');
    assert.ok(await page.evaluate(() => { const bounds = document.getElementById('chart-wrap').getBoundingClientRect(); return [...document.querySelectorAll('#chart circle')].every(dot => dot.getBoundingClientRect().right <= bounds.right); }), 'mobile data marks are visible without horizontal scrolling');
    await page.screenshot({ path: path.join(output, 'research-mobile.png'), fullPage: true });
    assert.ok(!requests.some(url => /analysis_covote_pairs|analysis_character_music_covote|templates[.]json/.test(url)), 'research never fetches raw matrices or desktop bundle');
    await choose('round', 'CN1');
    await choose('research-level', 'mrqap_coefficients');
    assert.equal(await page.locator('#result-table tbody tr').count(), 0);
    assert.match(await page.locator('#chart-note').innerText(), /尚未提供/);
    await choose('research-level', 'coverage');
    assert.match(await page.locator('#result-table tbody').innerText(), /unavailable_no_official_pair_data/);
    await page.click('#reset-button'); await ready();
    assert.equal(await page.locator('#analysis-kind').inputValue(), 'ranking');
    assert.equal(await page.locator('#research-controls').isVisible(), false);
    assert.ok(await page.locator('#result-table tbody tr').count() > 0);
    // Check a legacy desktop template and original CSV export after research.
    await choose('analysis-kind', 'desktop_compare');
    await choose('template', 'c02_selection_top');
    assert.ok(await page.locator('#result-table tbody tr').count() > 0);
    downloadPromise = page.waitForEvent('download');
    await page.click('#download-button'); download = await downloadPromise;
    assert.ok(fs.readFileSync(await download.path(), 'utf8').length > 100);
    // Real per-round shards keep the matrix/network regression small.
    for (const [template, chart] of [['a01_count_matrix', '热力图'], ['a02_network', '网络图'], ['a03_bubble', '气泡图'], ['a04_count_change', '条形图']]) {
      await choose('template', template);
      assert.equal(await page.locator('#summary-chart').innerText(), chart, template);
      assert.ok(await page.locator('#result-table tbody tr').count() > 0, template);
    }
    await choose('template', 'a02_network');
    assert.ok(await page.locator('#faction').isVisible());
    const faction = await page.locator('#faction option').nth(1).getAttribute('value');
    await choose('faction', faction);
    assert.equal(await page.locator('#faction').inputValue(), faction);
    // A slow research fetch cannot overwrite a newer ordinary selection.
    await page.route('**/web_data/research/coverage-*', async route => { await new Promise(resolve => setTimeout(resolve, 300)); await route.continue(); });
    await choose('analysis-kind', 'research');
    await choose('round', 'CN2');
    await page.selectOption('#research-level', 'coverage');
    await page.selectOption('#analysis-kind', 'ranking'); await ready();
    await page.waitForTimeout(500);
    assert.doesNotMatch(await page.locator('#chart-title').innerText(), /离线研究/);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', assertions: 'mobile lazy loading, filters, missing estimates, all-round scopes, CSV, reset, legacy network/matrix/bubble/change/factions using verified per-round shards, stale request guard', screenshots: output }));
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    console.error('UI state:', await page.locator('#status-line').innerText(), 'errors:', errors);
    throw error;
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
