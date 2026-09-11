const { chromium } = require('playwright')
const fs = require('node:fs')
const assert = require('node:assert/strict')
const path = require('node:path')
const root = path.resolve(__dirname, '../../tmp/week07-editions-product-ui')
fs.mkdirSync(root, { recursive: true })
const base = 'http://127.0.0.1:41734'
const api = 'http://127.0.0.1:18004/api'
;(async () => {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
  const page = await context.newPage()
  page.setDefaultTimeout(15000)
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  const checks = []
  const req = async (path, method = 'GET', data) => {
    const r = await context.request.fetch(api + path, { method, data })
    assert(r.ok(), await r.text())
    return (await r.json()).data
  }
  const shot = async (name) => {
    await page.screenshot({
      path: `${root}/${name}.png`,
      fullPage: !name.startsWith('editor'),
      animations: 'disabled',
    })
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
      false,
      'overflow ' + name,
    )
    checks.push(name)
  }
  try {
    for (let i = 0; i < 60; i++) {
      try {
        if ((await context.request.get(api + '/health')).ok()) break
      } catch {}
      await new Promise((r) => setTimeout(r, 1000))
    }
    assert.equal(
      (await (await context.request.get(api + '/health')).json()).environment,
      'week07-ui-test',
      'Only the isolated fixture server is allowed',
    )
    const suffix = Date.now().toString().slice(-7)
    const course = await req('/courses', 'POST', { name: '测试允许空间 ' + suffix })
    await req('/courses', 'POST', { name: '测试隔离空间 ' + suffix })
    await page.goto(base + '/agents')
    await page.getByRole('heading', { name: '智能体管理', exact: true }).waitFor()
    await page.getByRole('button', { name: '创建智能体', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '创建智能体', exact: true })
    assert.equal((await req('/agent-profiles/options')).edition, 'product')
    assert.equal(await dialog.getByText('研究记录（仅研发/科研模式）', { exact: true }).count(), 0)
    checks.push('product-editor-has-no-research-settings')
    await dialog.getByLabel('名称', { exact: true }).fill('版本测试 ' + suffix)
    await dialog.getByLabel('描述', { exact: true }).fill('用于隔离验收的智能体')
    await dialog.getByLabel('系统提示', { exact: true }).fill('使用版本一的简洁回答')
    await dialog.getByLabel('供应商', { exact: true }).selectOption('deepseek')
    await dialog.getByLabel('模型', { exact: true }).selectOption('fixture-a')
    await dialog.getByLabel(course.name, { exact: true }).check()
    await dialog.getByLabel('允许联网搜索', { exact: true }).uncheck()
    await dialog.getByLabel('问答返回数', { exact: true }).fill('7')
    await dialog.getByLabel('问答候选数', { exact: true }).fill('3')
    await dialog.getByRole('button', { name: '保存智能体' }).click()
    await dialog.getByRole('alert').filter({ hasText: '返回数量不能超过' }).waitFor()
    await dialog.getByLabel('问答返回数', { exact: true }).fill('2')
    await shot('editor-desktop')
    await dialog.getByRole('button', { name: '保存智能体' }).click()
    await dialog.waitFor({ state: 'hidden' })
    let profile = (await req('/agent-profiles')).find((p) => p.name === '版本测试 ' + suffix)
    assert(profile)
    let card = page
      .locator('.agent-card')
      .filter({ has: page.getByRole('heading', { name: profile.name, exact: true }) })
    await shot('agents-desktop')
    await card.getByRole('button', { name: '快速对话', exact: true }).click()
    await page.getByText('新会话使用 r1', { exact: false }).waitFor()
    await page.getByLabel('快速对话消息').fill('第一版的对话')
    await page.getByRole('button', { name: '发送消息', exact: true }).click()
    await page
      .locator('.assistant-message:not(.live-message)')
      .filter({ hasText: '模拟模型回复：fixture-a' })
      .waitFor()
    const aUrl = page.url()
    await page.getByText('固定版本 r1', { exact: false }).waitFor()
    await page.reload()
    await page.getByText('固定版本 r1', { exact: false }).waitFor()
    await shot('quick-bound-desktop')
    await page.goto(base + '/agents')
    card = page
      .locator('.agent-card')
      .filter({ has: page.getByRole('heading', { name: profile.name, exact: true }) })
    await card.getByRole('button', { name: '编辑', exact: true }).click()
    let edit = page.getByRole('dialog', { name: '编辑智能体' })
    await edit.getByLabel('系统提示', { exact: true }).fill('使用版本二的详细回答')
    await edit.getByLabel('模型', { exact: true }).selectOption('fixture-b')
    await edit.getByLabel('变更说明', { exact: true }).fill('切换到第二个模型')
    await edit.getByRole('button', { name: '保存智能体' }).click()
    await edit.waitFor({ state: 'hidden' })
    await card.getByRole('button', { name: '版本记录', exact: true }).click()
    let versions = page.getByRole('dialog', { name: '版本记录' })
    await versions.getByRole('button', { name: /r1 ·/ }).click()
    await versions.getByText('与当前版本相比：系统提示、供应商 / 模型').waitFor()
    await shot('versions-desktop')
    await versions.getByRole('button', { name: 'Close this dialog' }).click()
    await page.goto(aUrl)
    await page.getByText('固定版本 r1', { exact: false }).waitFor()
    await page.getByLabel('快速对话消息').fill('旧会话仍用第一版')
    await page.getByRole('button', { name: '发送消息', exact: true }).click()
    await page
      .locator('.assistant-message:not(.live-message)')
      .filter({ hasText: '模拟模型回复：fixture-a' })
      .nth(1)
      .waitFor()
    await page.goto(base + '/chat/new?agent=' + profile.id)
    await page.getByText('新会话使用 r2', { exact: false }).waitFor()
    await page.getByLabel('快速对话消息').fill('新会话第二版')
    await page.getByRole('button', { name: '发送消息', exact: true }).click()
    await page
      .locator('.assistant-message:not(.live-message)')
      .filter({ hasText: '模拟模型回复：fixture-b' })
      .waitFor()
    const bUrl = page.url()
    // Delay A's history fetch, navigate back to B, then deliver the stale response.
    const aPath = new URL(aUrl).pathname,
      bPath = new URL(bUrl).pathname
    const aApi = api + '/quick-conversations/' + aPath.split('/').pop()
    let releaseA
    const gate = new Promise((resolve) => {
      releaseA = resolve
    })
    await page.route(aApi, async (route) => {
      await gate
      await route.continue()
    })
    await page.locator(`a[href="${aPath}"]`).click()
    await page.locator(`a[href="${bPath}"]`).click()
    await page.getByText('固定版本 r2', { exact: false }).waitFor()
    const oldResponse = page.waitForResponse(aApi)
    releaseA()
    await oldResponse
    await page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
    )
    assert.equal(page.url(), bUrl)
    assert(await page.getByText('固定版本 r2', { exact: false }).isVisible())
    await page.unroute(aApi)
    checks.push('stale-conversation-response-isolation')

    await page.goto(base + '/assistant?agent=' + profile.id)
    await page.getByText('新会话使用 r2', { exact: false }).waitFor()
    const select = page.locator('.el-select').filter({ has: page.locator('#assistant-course') })
    await select.click()
    await page.getByRole('option', { name: course.name, exact: true }).waitFor()
    assert.equal(
      await page.getByRole('option', { name: '测试隔离空间 ' + suffix, exact: true }).count(),
      0,
    )
    await page.getByRole('option', { name: course.name, exact: true }).click()
    await shot('course-selection-desktop')
    await page.getByLabel('智能体请求', { exact: true }).fill('什么是测试空间')
    await page.locator('.question-composer button[type="submit"]').click()
    await page
      .locator('.answer-result:not(.live-result)')
      .filter({ hasText: '资料不足' })
      .first()
      .waitFor()
    await page.getByText('固定版本 r2', { exact: false }).waitFor()
    const courseConversationId = new URL(page.url()).pathname.split('/').pop()
    const courseHistory = await req(`/courses/${course.id}/conversations/${courseConversationId}`)
    assert.equal(
      courseHistory.agent_profile_revision_id,
      (await req('/agent-profiles/' + profile.id)).current_revision.id,
    )
    assert.equal(courseHistory.messages.at(-1).retrieval.agent_runtime.requested_model, 'fixture-b')
    assert.equal(courseHistory.messages.at(-1).answer_status, 'insufficient_evidence')
    await page.reload()
    await page.getByText('固定版本 r2', { exact: false }).waitFor()
    checks.push('course-bound-stream-and-refresh')

    await page.goto(base + '/agents')
    await card.getByRole('button', { name: '停用', exact: true }).click()
    await page.getByRole('button', { name: '确认', exact: true }).click()
    await card.getByText('已停用', { exact: true }).waitFor()
    await page.goto(bUrl)
    await page.getByRole('alert').filter({ hasText: '此智能体已停用' }).waitFor()
    await page.getByLabel('快速对话消息').fill('停用不能发送')
    assert(await page.getByRole('button', { name: '发送消息', exact: true }).isDisabled())
    assert(
      await page
        .locator('.assistant-message:not(.live-message)')
        .filter({ hasText: 'fixture-b' })
        .isVisible(),
    )
    checks.push('create-chat-edit-r1-r2-disable-history')
    await page.goto(base + '/agents')
    await card.getByRole('button', { name: '复制', exact: true }).click()
    await page.getByRole('button', { name: '复制', exact: true }).last().click()
    await page.getByRole('heading', { name: profile.name + ' 副本', exact: true }).waitFor()
    await card.getByRole('button', { name: '版本记录', exact: true }).click()
    versions = page.getByRole('dialog', { name: '版本记录' })
    await versions.getByRole('button', { name: /r1 ·/ }).click()
    await versions.getByRole('button', { name: '从此配置创建新版本' }).click()
    await page.getByRole('button', { name: '创建新版本', exact: true }).click()
    await versions.getByRole('button', { name: /r3 ·/ }).waitFor()
    await versions.getByRole('button', { name: 'Close this dialog' }).click()
    checks.push('copy-and-restore')
    await card.getByRole('button', { name: '编辑', exact: true }).click()
    edit = page.getByRole('dialog', { name: '编辑智能体' })
    profile = await req('/agent-profiles/' + profile.id)
    await req('/agent-profiles/' + profile.id, 'PATCH', {
      expected_row_version: profile.row_version,
      description: '并发修改',
    })
    await edit.getByLabel('描述', { exact: true }).fill('保留的未保存草稿')
    await edit.getByRole('button', { name: '保存智能体' }).click()
    await edit.getByRole('button', { name: '重新载入最新版本' }).waitFor()
    assert.equal(await edit.getByLabel('描述', { exact: true }).inputValue(), '保留的未保存草稿')
    await edit.getByRole('button', { name: '取消', exact: true }).click()
    checks.push('concurrent-edit-draft-preserved')
    await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
    await shot('agents-collapsed')
    await page.setViewportSize({ width: 390, height: 844 })
    await shot('agents-mobile')
    await page.getByRole('button', { name: '创建智能体', exact: true }).click()
    await page.getByRole('dialog', { name: '创建智能体', exact: true }).waitFor()
    await shot('editor-mobile')
    await page
      .getByRole('dialog', { name: '创建智能体' })
      .getByRole('button', { name: '取消', exact: true })
      .click()
    await page.getByRole('button', { name: '打开侧边栏', exact: true }).click()
    await page.getByRole('link', { name: '智能体管理', exact: true }).click()
    assert(!(await page.locator('.app-sidebar').getAttribute('class')).includes('mobile-open'))
    await page.goto(bUrl)
    await page.getByRole('alert').filter({ hasText: '此智能体已停用' }).waitFor()
    await shot('quick-mobile-disabled')
    const beforeInvalid = (await req('/quick-conversations')).length
    await page.goto(base + '/chat/00000000-0000-0000-0000-000000000000')
    await page.locator('.quick-error').waitFor()
    await page.getByLabel('快速对话消息').fill('无效会话不能误建默认会话')
    assert(await page.getByRole('button', { name: '发送消息', exact: true }).isDisabled())
    assert.equal((await req('/quick-conversations')).length, beforeInvalid)
    checks.push('invalid-history-cannot-create-legacy')
    await page.setViewportSize({ width: 1440, height: 1050 })
    await page.goto(base + '/agents')
    await card.getByRole('button', { name: '删除', exact: true }).click()
    let deletion = page.getByRole('dialog', { name: '删除智能体', exact: true })
    await deletion.waitFor()
    await shot('delete-confirm-desktop')
    await deletion.screenshot({ path: root + '/delete-confirm-desktop.png' })
    await deletion.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal((await req('/agent-profiles/' + profile.id)).deleted_at, null)
    checks.push('delete-cancel-preserves-profile')
    await card.getByRole('button', { name: '删除', exact: true }).click()
    profile = await req('/agent-profiles/' + profile.id)
    await req('/agent-profiles/' + profile.id, 'PATCH', {
      expected_row_version: profile.row_version, description: '删除前并发更新',
    })
    await deletion.getByRole('button', { name: '删除', exact: true }).click()
    await page.getByText('智能体已被修改，请刷新配置后重试。', { exact: false }).waitFor()
    assert.equal((await req('/agent-profiles/' + profile.id)).deleted_at, null)
    checks.push('delete-stale-version-conflict')
    await page.reload()
    await card.getByRole('button', { name: '删除', exact: true }).click()
    await deletion.getByRole('button', { name: '删除', exact: true }).click()
    await card.waitFor({ state: 'detached' })
    assert((await req('/agent-profiles/' + profile.id)).deleted_at)
    assert(!(await req('/agent-profiles')).some((item) => item.id === profile.id))
    await page.goto(base + '/chat/new')
    await page.getByLabel('选择智能体', { exact: true }).waitFor()
    assert.equal(await page.locator(`select option[value="${profile.id}"]`).count(), 0)
    checks.push('delete-hides-management-and-selector')
    await page.goto(bUrl)
    await page.getByRole('alert').filter({ hasText: '此智能体已删除' }).waitFor()
    await page.getByText('固定版本 r2', { exact: false }).waitFor()
    assert(await page.locator('.assistant-message:not(.live-message)').filter({ hasText: 'fixture-b' }).isVisible())
    await page.getByLabel('快速对话消息').fill('已删除不能继续')
    assert(await page.getByRole('button', { name: '发送消息', exact: true }).isDisabled())
    await shot('deleted-history-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await shot('deleted-history-mobile')
    assert.deepEqual(errors, [])
    fs.writeFileSync(root + '/result.json', JSON.stringify({ checks, errors, aUrl, bUrl }, null, 2))
    console.log(JSON.stringify({ checks, errors }))
  } catch (error) {
    await page.screenshot({ path: root + '/failure.png', fullPage: true, animations: 'disabled' })
    console.error(error)
    process.exitCode = 1
  } finally {
    await browser.close()
  }
})()
