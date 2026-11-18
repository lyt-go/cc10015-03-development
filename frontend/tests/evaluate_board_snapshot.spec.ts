import { expect, test } from '@playwright/test'

test('评估看板聚合快照：概览/明细一致、口径唯一、实验展开、失败保留与续写', async ({ page }) => {
  test.setTimeout(300_000)
  const browserErrors: string[] = []
  page.on('pageerror', (error) => browserErrors.push(error.message))
  page.on('response', (response) => {
    if (response.url().includes('/api/') && response.status() >= 400) {
      browserErrors.push(`${response.status()} ${response.url()}`)
    }
  })

  await page.goto('/evaluate_board')
  await expect(page.getByTestId('kpi-card').first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('snapshot-overview')).toBeVisible()

  // 概览：每份快照独立排列，卡片只引用一个登记口径
  const previewCards = page.locator('.snapshot-panel .metric-card')
  expect(await previewCards.count()).toBeGreaterThanOrEqual(3)
  const caliberText = await previewCards.first().locator('.caliber-line').innerText()
  expect(caliberText).toMatch(/口径 v\d+ · ALIAS-/)
  await expect(previewCards.first().locator('.conflict-badge')).toContainText('统一')

  // 卡片展开到对应实验快照
  await previewCards.first().click()
  await expect(page.getByTestId('card-expand')).toBeVisible()
  const expandRows = page.getByTestId('card-expand').locator('tbody tr')
  expect(await expandRows.count()).toBeGreaterThanOrEqual(1)

  // 明细视图：列表入口与详情面板结果一致
  await page.getByTestId('tab-detail').click()
  await expect(page.getByTestId('snapshot-detail')).toBeVisible()
  const rows = page.locator('tr[data-testid^="snapshot-row-"]')
  const rowCount = await rows.count()
  expect(rowCount).toBeGreaterThanOrEqual(3)
  const firstRowText = await rows.first().innerText()
  const snapshotCode = firstRowText.split('\t')[0]
  await rows.first().getByRole('button', { name: '查看详情' }).click()
  await expect(page.getByTestId('snapshot-detail-panel')).toBeVisible()
  await expect(page.getByTestId('snapshot-detail-panel')).toContainText(snapshotCode)
  const detailCards = page.getByTestId('snapshot-detail-panel').locator('.data-table').first().locator('tbody tr')
  expect(await detailCards.count()).toBeGreaterThanOrEqual(1)
  await page.getByTestId('close-detail').click()

  // 核对：已发布快照核对通过并留档
  await page.getByTestId('verify-snapshot').click()
  await expect(page.getByTestId('verification-result')).toBeVisible()
  await expect(page.getByTestId('verification-result')).toContainText('通过')

  // 刷新成功：切回概览后最新快照发布
  await page.getByTestId('tab-overview').click()
  await expect(page.getByTestId('snapshot-overview')).toBeVisible()
  await page.getByTestId('refresh-snapshots').click()
  await expect(page.locator('.snapshot-panel').first()).toHaveAttribute('data-published', 'true')

  // 模拟失败：保留上一完整快照并给出未完成实验
  await page.getByPlaceholder('例如 EXPE-0002，留空表示全部成功').fill('EXPE-0002')
  await page.getByTestId('run-analysis').click()
  await expect(page.getByTestId('board-error')).toBeVisible()
  const failedPanel = page.locator('.snapshot-panel[data-published="false"]').first()
  await expect(failedPanel).toContainText('上一完整快照')
  await expect(failedPanel).toContainText('EXPE-0002')
  await expect(page.locator('.snapshot-panel[data-published="true"]').first()).toBeVisible()
  const failedId = await failedPanel.getAttribute('data-testid')

  // 恢复：清掉模拟失败后按未完成实验续写，该份快照重新发布
  await page.getByPlaceholder('例如 EXPE-0002，留空表示全部成功').fill('')
  await failedPanel.getByRole('button', { name: '按未完成实验续写' }).click()
  await expect(page.getByTestId(failedId as string)).toHaveAttribute('data-published', 'true')
  await expect(page.getByTestId(failedId as string)).toContainText('已完成')

  expect(browserErrors).toEqual([])
})
