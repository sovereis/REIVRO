const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
let server, browser, origin;
before(async () => {
  server = spawn(process.env.PYTHON || 'python', ['-B','-m','tests.ui.serve_fixture'], {env:process.env, cwd:require('node:path').resolve(__dirname, '../..')});
  origin = await new Promise((resolve,reject) => {
    server.stdout.once('data', data => resolve(data.toString().trim()));
    server.stderr.on('data', data => process.stderr.write(data));
    server.once('exit', code => reject(new Error('Server exited '+code)));
  });
  browser = await chromium.launch({headless:true, executablePath:process.env.SCOP_CHROMIUM || undefined});
});
after(async () => {await browser?.close(); server?.kill();});

test('real pipeline renders evidence, saves explicit feedback and preserves unknown metrics', async () => {
  const page = await browser.newPage();
  await page.goto(origin);
  await page.getByLabel('Public GitHub pull request URL').fill('https://github.com/pallets/flask/pull/5808');
  await page.locator('#github-consent').check();
  await page.locator('#record-consent').check();
  await page.locator('#run-button').click();
  await page.getByRole('heading', {name:'Workflow completed',exact:true}).waitFor({timeout:90000});
  assert.match(await page.locator('#result').innerText(), /pr-source-summary/);
  assert.equal(await page.locator('#result ol li').count(),4);
  assert.ok(await page.locator('#result a').count() > 0);
  await page.getByText('Workflow steps and timing', {exact:true}).click();
  await page.locator('.claim summary').first().click();
  assert.ok(await page.getByText('Exact source excerpt', {exact:true}).first().isVisible());
  assert.ok(await page.getByText('Review whether each excerpt', {exact:false}).isVisible());
  assert.equal(await page.locator('#result img').count(),0);
  if (!process.env.SCOP_UI_LIVE) assert.match(await page.locator('#result').textContent(), /<img src=x onerror=alert\(1\)>/);
  if (process.env.SCOP_UI_LIVE) console.log('LIVE RESULT:', await page.locator('#status').innerText(), await page.locator('#result').innerText());
  if (process.env.SCOP_UI_LIVE) await page.screenshot({path:'/tmp/scop-workspace-live-unreviewed.png',fullPage:true});
  await page.locator('#decision').selectOption('accepted');
  await page.locator('#feedback-consent').check();
  await page.getByRole('button',{name:'Save evaluation'}).click();
  await page.getByText('Saved: accepted. Technical status remains completed.',{exact:true}).waitFor();
  await page.locator('#load-measurements').click();
  await page.getByText('1 recorded attempts · 1 human evaluations',{exact:true}).waitFor();
  assert.match(await page.locator('#measurements').innerText(),/Review: Unknown/);
  assert.match(await page.locator('#measurements').innerText(),/Partial; human timing missing/);
  await page.screenshot({path:process.env.SCOP_SCREENSHOT || '/tmp/scop-workspace.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth));
  await page.close();
});

test('permission denial and invalid URL never appear successful', async () => {
  const page = await browser.newPage(); await page.goto(origin);
  await page.locator('#pr-url').fill('https://github.com/pallets/flask/pull/5808');
  await page.locator('#run-button').click();
  await page.getByRole('heading',{name:'Workflow blocked',exact:true}).waitFor();
  assert.equal(await page.locator('#feedback-panel').isVisible(),false);
  await page.locator('#github-consent').check();
  const requests = [];
  page.on('request', request => {
    if (request.url().endsWith('/api/run')) requests.push(request);
  });
  for (const url of ['https://example.com/invalid', 'https://github.com/a/b/pull/0',
    'https://github.com/../b/pull/1', 'https://github.com/a/b/pull/1/files',
    'https://github.com/a/b/pull/1?x=1', 'https://github.com/a/b/pull/1#diff']) {
    await page.locator('#pr-url').fill(url);
    await page.locator('#run-button').click();
    assert.ok(await page.getByRole('alert').isVisible());
    assert.equal(await page.locator('#pr-url').getAttribute('aria-invalid'), 'true');
    assert.ok(await page.locator('#pr-url').evaluate(node => node === document.activeElement));
  }
  assert.equal(requests.length, 0);
  assert.equal(await page.getByRole('heading',{name:'Pull request summary',exact:true}).count(),0);
  await page.close();
});

test('unavailable source is blocked, with no invented summary', {skip:!!process.env.SCOP_UI_LIVE}, async () => {
  const page = await browser.newPage(); await page.goto(origin);
  await page.locator('#pr-url').fill('https://github.com/pallets/flask/pull/404');
  await page.locator('#github-consent').check(); await page.locator('#run-button').click();
  await page.getByRole('heading',{name:'Workflow blocked',exact:true}).waitFor();
  assert.match(await page.locator('#result').innerText(), /github_unavailable/);
  assert.equal(await page.getByRole('heading',{name:'Pull request summary',exact:true}).count(),0);
  await page.close();
});

 test('failed verification and actual interruption withhold success and feedback', {skip:!!process.env.SCOP_UI_LIVE}, async () => {
  const page = await browser.newPage(); await page.goto(origin);
  await page.locator('#github-consent').check();
  for (const [number,state] of [[405,'failed'],[406,'cancelled']]) {
    await page.locator('#pr-url').fill('https://github.com/pallets/flask/pull/'+number);
    await page.locator('#run-button').click();
    await page.getByRole('heading',{name:'Workflow '+state,exact:true}).waitFor();
    assert.equal(await page.getByRole('heading',{name:'Pull request summary',exact:true}).count(),0);
    assert.equal(await page.locator('#feedback-panel').isVisible(),false);
  }
  await page.close();
});

test('keyboard access, safe citation URLs and no implicit external browser requests', async () => {
  const page = await browser.newPage(); const external = [];
  page.on('request', request => {if (!request.url().startsWith(origin + '/')) external.push(request.url());});
  await page.goto(origin);
  await page.keyboard.press('Tab');
  assert.ok(await page.getByRole('link', {name:'Skip to main content'}).evaluate(node => node === document.activeElement));
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('.brand').evaluate(node => node === document.activeElement),true);
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('#pr-url').evaluate(node => node === document.activeElement),true);
  await page.evaluate(() => {
    const parent = document.getElementById('result');
    for (const url of ['javascript:alert(1)','https://evil.example','https://github.com@evil.example'])
      citation({url,kind:'diff',locator:'x',excerpt:'<script>alert(1)</script>'},parent);
    parent.hidden = false;
  });
  assert.equal(await page.locator('#result a, #result script').count(),0);
  assert.equal(external.length,0); await page.close();
});

test('without a store, recording is disabled and an unrecorded review completes', async () => {
  const noStore = spawn(process.env.PYTHON || 'python', ['-B','-m','tests.ui.serve_fixture'], {
    env:{...process.env, SCOP_UI_NO_STORE:'1'}, cwd:require('node:path').resolve(__dirname, '../..')
  });
  const page = await browser.newPage();
  try {
    const address = await new Promise((resolve, reject) => {
      noStore.stdout.once('data', data => resolve(data.toString().trim()));
      noStore.once('error', reject);
      noStore.once('exit', code => reject(new Error('Server exited '+code)));
    });
    await page.goto(address);
    assert.ok(await page.locator('#record-consent').isDisabled());
    assert.ok(await page.locator('#load-measurements').isDisabled());
    assert.match(await page.locator('#store-help').innerText(), /You can still review PRs/);
    await page.locator('#pr-url').fill('https://github.com/pallets/flask/pull/5808');
    await page.locator('#github-consent').check();
    const sent = page.waitForRequest(request => request.url().endsWith('/api/run'));
    await page.locator('#run-button').click();
    const payload = (await sent).postDataJSON();
    assert.equal(payload.record_measurement, false);
    assert.deepEqual(payload.permissions, []);
    await page.getByRole('heading', {name:'Workflow completed',exact:true}).waitFor();
    assert.equal(await page.locator('#feedback-panel').isVisible(), false);
  } finally {
    await page.close();
    noStore.kill();
  }
});
