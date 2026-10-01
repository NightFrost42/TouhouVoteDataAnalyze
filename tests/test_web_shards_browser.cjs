/* Fixed browser assertions. Run with Playwright; BROWSER_CHANNEL is optional. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const root = path.resolve(process.env.WEB_ROOT || path.join(__dirname, '..'));
const output = path.join(__dirname, '.tmp-web-performance');
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
  const browser = await chromium.launch({headless:true, args:['--enable-precise-memory-info']});
  const context = await browser.newContext({viewport:{width:1280,height:900},acceptDownloads:true});
  const page = await context.newPage(); const requests=[],errors=[];
  page.on('request',r=>requests.push(new URL(r.url()).pathname)); page.on('pageerror',e=>errors.push(e.message));
  const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#loading-state').classList.contains('hidden'),null,{timeout:120000}); assert.ok(!(await page.locator('#status-line').getAttribute('class')||'').includes('error-text'));};
  const choose=async(id,value)=>{await page.selectOption('#'+id,value); await ready();};
  const report={};
  try {
    let t=Date.now(); await page.goto(`http://127.0.0.1:${server.address().port}/vote_explorer_web/`,{waitUntil:'networkidle'});await ready();
    report.home={ms:Date.now()-t,requests:requests.length,heap:await page.evaluate(()=>performance.memory.usedJSHeapSize)};
    assert.ok(!requests.some(u=>/web_data|analysis_covote_pairs|entity_questionnaire|comments[.]csv/.test(u)));
    await choose('analysis-kind','desktop_compare');
    for(const key of ['c13_comments_top','c14_comment_unique_rate','c15_comment_length']){await choose('template',key);assert.ok(await page.locator('#result-table tbody tr').count()>0);}
    assert.ok(!requests.some(u=>u.includes('/tables/')),'comments must not load network or questionnaire tables');
    await page.fill('#top-n','100'); await ready();
    const first=requests.length; t=Date.now(); await choose('template','a02_network');
    report.network={ms:Date.now()-t,requests:requests.slice(first),nodes:await page.locator('#chart circle').count(),heap:await page.evaluate(()=>performance.memory.usedJSHeapSize)};
    assert.equal(report.network.nodes,100); assert.ok(report.network.heap<512*1024*1024,'100-node heap budget is 512 MiB');
    const index=JSON.parse(fs.readFileSync(path.join(root,'vote_explorer_web/web_data/tables/index.json'),'utf8'));
    const permitted=new Set(index.entries[JSON.stringify(['covote_pairs','CN11','character'])].map(e=>'/vote_explorer_web/web_data/tables/'+e.path));
    assert.ok(report.network.requests.filter(u=>u.includes('/tables/')&&!u.endsWith('index.json')).every(u=>permitted.has(u)));
    t=Date.now(); await choose('network-node-size','pagerank'); report.rerender_ms=Date.now()-t;
    await choose('template','a01_count_matrix'); assert.equal(await page.locator('#result-table tbody tr').count(),100);
    const pending=page.waitForEvent('download');t=Date.now();await page.click('#download-button');const download=await pending;const csv=fs.readFileSync(await download.path(),'utf8');
    report.matrix={download_ms:Date.now()-t,bytes:Buffer.byteLength(csv)};
    assert.equal(await page.evaluate(s=>parseCSV(s).length,csv),100);
    for(const round of ['CN10','JP22','CN11']){await choose('round',round);await choose('template','a02_network');assert.ok(await page.locator('#chart circle').count()>0);}
    assert.ok(await page.evaluate(()=>tableLoader.cacheSize()<=2));
    await choose('template','a04_count_change');assert.ok(await page.locator('#result-table tbody tr').count()>0);
    await choose('template','r09_character_question_matrix');assert.ok(await page.locator('#result-table tbody tr').count()>0);
    await choose('template','m07_character_music_covote');assert.ok(await page.locator('#result-table tbody tr').count()>0);
    await page.click('#reset-button');await ready();assert.equal(await page.evaluate(()=>tableLoader.cacheSize()),0);
    assert.ok(!requests.some(u=>/analysis_covote_pairs|analysis_entity_questionnaire|analysis_character_music_covote/.test(u)),'never fetch full heavy CSVs');
    assert.deepEqual(errors,[]);report.status='PASS';fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  } finally {await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
