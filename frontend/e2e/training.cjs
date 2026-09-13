// Run once against fresh training-server.py fixtures; see training-ui-workflow.md.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const repo = path.resolve(__dirname, '../..')
const ROOT = path.resolve(repo, 'tmp', process.env.AGENTIC_TRAINING_UI_DIR || 'week08-training-ui')
assert(
  ROOT.startsWith(path.resolve(repo, 'tmp') + path.sep),
  'Fixture output must remain inside tmp',
)
fs.mkdirSync(ROOT, { recursive: true })
const url = 'http://127.0.0.1:15174'
const samples = [
  {
    id: 'a',
    source_id: 'fruit',
    group_id: 'fruit',
    split: 'train',
    query: '苹果是什么颜色',
    document: '成熟苹果具有红色果皮和可食用果肉。',
    relevance: 1,
  },
  {
    id: 'b',
    source_id: 'planet',
    group_id: 'planet',
    split: 'validation',
    query: '行星如何公转',
    document: '引力使天体沿着椭圆轨道围绕恒星运动。',
    relevance: 0,
  },
]
const cases = [],
  errors = []
let browser, page, context
async function text(s) {
  await page.getByText(s, { exact: true }).first().waitFor({ state: 'visible', timeout: 15000 })
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
async function approve() {
  await page.getByLabel('审核人', { exact: true }).fill('合成验收人')
  await page
    .getByLabel('审核说明', { exact: true })
    .fill('已核对本地合成文本、来源许可和隐私；不含正式业务数据。')
  await page.getByRole('button', { name: '提交审核', exact: true }).click()
  await page.getByRole('button', { name: '批准此版本', exact: true }).waitFor()
  await page.getByRole('button', { name: '批准此版本', exact: true }).click()
  await page.getByRole('button', { name: '撤销审核', exact: true }).waitFor()
}
async function wizard(seed = 42, steps = 3) {
  await page.goto(url + '/training/new')
  await page.getByLabel('智能体', { exact: true }).selectOption({ label: '合成科研助手 · r1' })
  await page.getByText('固定版本', { exact: true }).waitFor()
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await page.getByLabel('数据集', { exact: true }).selectOption({ label: 'Day4 浏览器合成样本' })
  const options = page.getByLabel('已审核版本', { exact: true }).locator('option')
  await options.nth(1).waitFor({ state: 'attached' })
  await page.getByLabel('已审核版本', { exact: true }).selectOption({ index: 1 })
  await text('当前数据具备使用资格')
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await text('确认训练目标')
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await page.getByLabel('模拟步数', { exact: true }).fill(String(steps))
  await page.getByLabel('随机种子', { exact: true }).fill(String(seed))
  await page.getByLabel('秩 rank', { exact: true }).fill('0')
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: '超出允许范围' }).waitFor()
  await page.getByLabel('秩 rank', { exact: true }).fill('8')
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await text('复核后提交')
}
async function submit() {
  await page.getByRole('button', { name: '创建模拟训练任务', exact: true }).click()
  await page.waitForURL(/\/training\/runs\/[0-9a-f-]+/)
  return page.url().split('/').pop()
}
;(async () => {
  browser = await chromium.launch({ headless: true })
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.route('**/*', (route) => {
    const target = new URL(route.request().url())
    return ['127.0.0.1', 'localhost'].includes(target.hostname) ? route.continue() : route.abort()
  })
  page = await context.newPage()
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
  await page.goto(url + '/training/datasets')
  await page.getByRole('button', { name: '刷新列表', exact: true }).waitFor()
  await page.waitForFunction(() =>
    [...document.querySelectorAll('button')].some(
      (b) => b.textContent.trim() === '刷新列表' && !b.disabled,
    ),
  )
  if (await page.getByRole('button', { name: /Day4 浏览器合成样本/ }).count()) {
    await page
      .getByRole('button', { name: /Day4 浏览器合成样本/ })
      .first()
      .click()
  } else {
    await page.getByLabel('新数据集名称', { exact: true }).fill('Day4 浏览器合成样本')
    await page.getByRole('button', { name: '创建数据集', exact: true }).click()
  }
  await page.getByRole('heading', { name: '登记新版本', exact: true }).waitFor()
  await page.getByLabel('来源说明', { exact: true }).fill('本地浏览器验收合成文本')
  await page.getByLabel('许可标识', { exact: true }).fill('synthetic-owned')
  await page
    .getByLabel('许可及用途说明', { exact: true })
    .fill('自行编写的合成样本，仅用于本地验收。')
  await page.getByLabel('隐私状态', { exact: true }).selectOption('clean')
  await page.getByLabel('隐私复核说明', { exact: true }).fill('合成内容，无个人信息。')
  await page.getByLabel('确认来源许可允许训练', { exact: true }).check()
  await page.getByLabel('样本输入方式', { exact: true }).selectOption('paste')
  await page
    .getByLabel('样本 JSONL', { exact: true })
    .fill(samples.map((s) => JSON.stringify({ ...s, split: 'test' })).join('\n'))
  await page.getByRole('button', { name: '校验样本', exact: true }).click()
  await text('格式校验未通过')
  assert(await page.getByRole('button', { name: '登记新版本', exact: true }).isDisabled())
  cases.push('test split rejected in browser')
  await page
    .getByLabel('样本 JSONL', { exact: true })
    .fill(samples.map((s) => JSON.stringify(s)).join('\n'))
  await page.getByRole('button', { name: '校验样本', exact: true }).click()
  await text('格式校验通过')
  await page.getByRole('button', { name: '登记新版本', exact: true }).click()
  await page.getByRole('button', { name: '提交审核', exact: true }).waitFor()
  await approve()
  await shot('datasets-approved')
  cases.push('dataset validate register review approve')
  await wizard()
  await shot('wizard-review')
  let interrupted = false,
    createdId
  const requestKeys = []
  await page.route('**/api/training-runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    requestKeys.push(route.request().postDataJSON().idempotency_key)
    if (!interrupted) {
      interrupted = true
      const response = await route.fetch()
      assert.equal(response.status(), 201)
      createdId = (await response.json()).data.id
      return route.abort('failed')
    }
    return route.continue()
  })
  await page.getByRole('button', { name: '创建模拟训练任务', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: '输入已保留' }).waitFor()
  await text('复核后提交')
  const runId = await submit()
  assert.equal(runId, createdId)
  assert.equal(requestKeys.length, 2)
  assert.equal(requestKeys[0], requestKeys[1])
  await page.unroute('**/api/training-runs')
  await text('模拟成功')
  await page.reload()
  await text('模拟成功')
  await shot('run-success')
  cases.push('five steps invalid parameter lost response idempotent retry refresh')
  await page.getByRole('button', { name: '查看模拟产物', exact: true }).click()
  await page.waitForURL(/\/training\/adapters\/[0-9a-f-]+/)
  await text('文件有效')
  const adapterUrl = page.url()
  assert.equal(await page.getByRole('button', { name: /部署|启用到/ }).count(), 0)
  await shot('adapter-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(
    () => getComputedStyle(document.querySelector('.workspace')).marginLeft === '0px',
  )
  await shot('adapter-mobile')
  assert(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    'Mobile horizontal overflow',
  )
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.waitForFunction(
    () => getComputedStyle(document.querySelector('.workspace')).marginLeft === '262px',
  )
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await page.waitForFunction(
    () => getComputedStyle(document.querySelector('.workspace')).marginLeft === '76px',
  )
  await shot('adapter-collapsed')
  cases.push('adapter source desktop mobile collapsed no deployment')
  await wizard(42, 100)
  const cancelId = await submit()
  await text('模拟运行中')
  await context.setOffline(true)
  await page.getByRole('alert').waitFor({ timeout: 12000 })
  await context.setOffline(false)
  await page.getByRole('alert').waitFor({ state: 'hidden', timeout: 12000 })
  await page.getByRole('button', { name: '取消模拟任务', exact: true }).click()
  await text('已取消')
  await shot('run-cancelled')
  cases.push('offline recovery and running cancellation')
  await wizard(13, 3)
  const failId = await submit()
  await text('失败')
  await page.getByRole('button', { name: '重试为新任务', exact: true }).click()
  await page.waitForURL(
    (u) => u.pathname.startsWith('/training/runs/') && !u.pathname.endsWith(failId),
  )
  const retryId = page.url().split('/').pop()
  await text('模拟成功')
  await shot('run-retried')
  cases.push('trusted fake failure retry new run retains source')
  await wizard(42, 100)
  const revokedId = await submit()
  await text('模拟运行中')
  await page.goto(url + '/training/datasets')
  await page.getByRole('button', { name: /Day4 浏览器合成样本/ }).click()
  await page.getByRole('button', { name: '撤销审核', exact: true }).waitFor()
  await page.getByLabel('审核人', { exact: true }).fill('合成验收人')
  await page.getByLabel('审核说明', { exact: true }).fill('验证撤销审核会停止正在运行的合成任务。')
  await page.getByRole('button', { name: '撤销审核', exact: true }).click()
  await page.getByRole('button', { name: '提交审核', exact: true }).waitFor()
  await page.goto(url + '/training/runs/' + revokedId)
  await text('已取消')
  await page.getByText('数据审核资格已撤销', { exact: true }).first().waitFor()
  cases.push('review revocation cancels running task')
  await page.goto(url + '/training/new')
  await page.getByLabel('智能体', { exact: true }).selectOption({ label: '合成科研助手 · r1' })
  await page.getByText('固定版本', { exact: true }).waitFor()
  await page.getByRole('button', { name: '下一步', exact: true }).click()
  await page.getByLabel('数据集', { exact: true }).selectOption({ label: 'Day4 浏览器合成样本' })
  await page.getByText('当前没有已审核版本。', { exact: false }).waitFor()
  await shot('wizard-revoked-empty')
  assert.equal(await page.getByLabel('已审核版本', { exact: true }).locator('option').count(), 1)
  cases.push('revoked version cannot be selected')
  await page.goto(adapterUrl)
  await text('文件有效')
  await page.getByRole('button', { name: '归档产物', exact: true }).click()
  await page.getByRole('button', { name: '确认归档', exact: true }).click()
  await text('已归档')
  await page.goto(url + '/training/adapters')
  assert.equal(
    await page
      .getByRole('link', { name: adapterUrl.split('/').pop().slice(0, 8), exact: true })
      .count(),
    0,
  )
  await page.getByLabel('包含已归档产物', { exact: true }).check()
  await page
    .getByRole('link', { name: adapterUrl.split('/').pop().slice(0, 8), exact: true })
    .waitFor()
  cases.push('archive retained and visible with filter')
  assert.deepEqual(errors, [])
  fs.writeFileSync(
    ROOT + '/browser-results.json',
    JSON.stringify(
      { cases, runId, cancelId, failId, retryId, revokedId, adapterUrl, errors },
      null,
      2,
    ),
  )
  console.log(JSON.stringify({ passed: cases.length, cases, errors }))
  await browser.close()
})().catch(async (e) => {
  console.error(e.stack)
  if (page) {
    await shot('browser-failure').catch(() => {})
    console.error((await page.locator('body').innerText()).slice(-6000))
  }
  if (browser) await browser.close()
  process.exit(1)
})
