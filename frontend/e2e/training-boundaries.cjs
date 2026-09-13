// Run after training.cjs in the same isolated fixtures.
const { chromium } = require('playwright')
const fs = require('node:fs')
const assert = require('node:assert/strict')
const path = require('node:path')
const repo = path.resolve(__dirname, '../..')
const ROOT = path.resolve(repo, 'tmp', process.env.AGENTIC_TRAINING_UI_DIR || 'week08-training-ui')
assert(
  ROOT.startsWith(path.resolve(repo, 'tmp') + path.sep),
  'Fixture output must remain inside tmp',
)
fs.mkdirSync(ROOT, { recursive: true })
const base = 'http://127.0.0.1:15174'
let browser, page
const cases = [],
  errors = []
async function shown(s) {
  await page.getByText(s, { exact: true }).first().waitFor()
}
async function shot(name) {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: ROOT + '/' + name + '.png',
    fullPage: true,
    animations: 'disabled',
    style: '#__vue-devtools-container__ { visibility: hidden !important; }',
  })
}
;(async () => {
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', (e) => errors.push(e.message))
  page.setDefaultTimeout(15000)
  for (const port of [18084, 18085]) {
    const response = await page.request.get('http://127.0.0.1:' + port + '/api/health')
    assert.equal(
      (await response.json()).environment,
      'week08-day04-isolated',
      'Only isolated fixture servers are allowed',
    )
  }
  await page.goto('http://127.0.0.1:15175/agents')
  await page.getByRole('heading', { name: '智能体管理', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '模拟微调', exact: true }).count(), 0)
  assert.equal(await page.getByRole('link', { name: '微调实验室', exact: true }).count(), 0)
  const trainingRequests = []
  page.on('request', (r) => {
    if (/api\/(training-datasets|training-runs|model-adapters)/.test(r.url()))
      trainingRequests.push(r.url())
  })
  await page.goto('http://127.0.0.1:15175/training/new')
  await shown('此功能仅在科研版提供')
  assert.deepEqual(trainingRequests, [])
  for (const path of ['training-datasets', 'training-runs', 'model-adapters']) {
    const r = await page.request.get('http://127.0.0.1:18085/api/' + path)
    assert.equal(r.status(), 403)
  }
  await shot('product-boundary')
  cases.push('product hides entry direct URL does not fetch research data API returns 403')
  await page.goto(base + '/training/datasets')
  await page.getByRole('button', { name: '刷新列表', exact: true }).waitFor()
  await page.getByLabel('新数据集名称', { exact: true }).fill('Day4 文件上传验收')
  await page.getByRole('button', { name: '创建数据集', exact: true }).click()
  await page.getByRole('heading', { name: '登记新版本', exact: true }).waitFor()
  await page.getByLabel('来源说明', { exact: true }).fill('自行编写的独立合成文本')
  await page.getByLabel('许可标识', { exact: true }).fill('synthetic-owned')
  await page.getByLabel('许可及用途说明', { exact: true }).fill('仅用于本地浏览器界面验收。')
  await page.getByLabel('隐私状态', { exact: true }).selectOption('clean')
  await page.getByLabel('隐私复核说明', { exact: true }).fill('无个人信息。')
  await page.getByLabel('确认来源许可允许训练', { exact: true }).check()
  const rows = [
    {
      id: 'file-a',
      source_id: 'tree',
      group_id: 'tree',
      split: 'train',
      query: '树木如何获取光照',
      document: '绿色叶片接受阳光以进行光合作用。',
      relevance: 1,
    },
    {
      id: 'file-b',
      source_id: 'sound',
      group_id: 'sound',
      split: 'validation',
      query: '声音怎样传播',
      document: '声波依靠介质振动传递能量。',
      relevance: 0,
    },
  ]
  await page.getByLabel('样本 JSONL 文件', { exact: true }).setInputFiles({
    name: 'synthetic.jsonl',
    mimeType: 'application/jsonl',
    buffer: Buffer.from(rows.map((x) => JSON.stringify(x)).join('\n')),
  })
  await page.getByRole('button', { name: '校验样本', exact: true }).click()
  await shown('格式校验通过')
  await page.getByRole('button', { name: '登记新版本', exact: true }).click()
  await page.getByRole('button', { name: '提交审核', exact: true }).waitFor()
  await page.getByLabel('审核人', { exact: true }).fill('文件上传验收人')
  await page
    .getByLabel('审核说明', { exact: true })
    .fill('合成样本来源、许可、隐私和划分均已核对。')
  await page.getByRole('button', { name: '提交审核', exact: true }).click()
  await page.getByRole('button', { name: '批准此版本', exact: true }).click()
  await page.getByRole('button', { name: '撤销审核', exact: true }).waitFor()
  cases.push('actual JSONL file upload validate register approve')
  await page.goto(base + '/agents')
  await page.getByRole('button', { name: '模拟微调', exact: true }).nth(1).waitFor()
  await page.getByRole('button', { name: '模拟微调', exact: true }).nth(1).click()
  await page.waitForURL(/\/training\/new\?agent=/)
  await shown('固定版本')
  const selected = await page
    .getByLabel('智能体', { exact: true })
    .locator('option:checked')
    .innerText()
  console.log({ selected })
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await page.getByLabel('数据集', { exact: true }).selectOption({ label: 'Day4 文件上传验收' })
  await page
    .getByLabel('已审核版本', { exact: true })
    .locator('option')
    .nth(1)
    .waitFor({ state: 'attached' })
  await page.getByLabel('已审核版本', { exact: true }).selectOption({ index: 1 })
  await shown('当前数据具备使用资格')
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await shown('复核后提交')
  await shot('wizard-review-stable')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(
    () => getComputedStyle(document.querySelector('.workspace')).marginLeft === '0px',
  )
  await shot('wizard-mobile-stable')
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.waitForFunction(
    () => getComputedStyle(document.querySelector('.workspace')).marginLeft !== '0px',
  )
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await page.waitForFunction(
    () => getComputedStyle(document.querySelector('.workspace')).marginLeft === '76px',
  )
  await shot('wizard-collapsed-stable')
  cases.push('agent entry selects revision five step review mobile and collapsed layout')
  await page.route('**/api/agent-profiles?*', async (route) => {
    const r = await route.fetch()
    const body = await r.json()
    body.data = []
    await route.fulfill({ response: r, json: body })
  })
  await page.goto(base + '/training/new')
  await page.getByText('没有可选的启用智能体。', { exact: false }).waitFor()
  await shot('wizard-no-agents')
  cases.push('empty enabled agent list gives recovery guidance')
  assert.deepEqual(errors, [])
  fs.writeFileSync(
    ROOT + '/browser-extra-results.json',
    JSON.stringify({ cases, errors, selected }, null, 2),
  )
  console.log(JSON.stringify({ passed: cases.length, cases, errors }))
  await browser.close()
})().catch(async (e) => {
  console.error(e)
  if (page) {
    await shot('extra-failure').catch(() => {})
    console.error((await page.locator('body').innerText()).slice(-4000))
  }
  if (browser) await browser.close()
  process.exit(1)
})
