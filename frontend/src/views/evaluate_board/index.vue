<template>
  <section class="page" data-module="evaluate_board">
    <header class="page-head">
      <div>
        <h2>评估看板</h2>
        <p class="page-desc">
          按看板配置读取 AB 对比结果表与留存矩阵，聚合生成看板聚合快照；每张指标卡只引用一个已登记口径，
          并可展开到对应实验快照。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" data-testid="refresh-snapshots" @click="refreshAll">
          刷新看板快照
        </button>
        <button class="btn" type="button" data-testid="verify-snapshot" @click="verifyCurrent">
          核对当前快照
        </button>
        <button class="btn" type="button" data-testid="export" @click="exportRows">导出看板配置</button>
      </div>
    </header>

    <div class="analysis-summary">
      <article v-for="m in summaryMetrics" :key="m.label" class="analysis-card" data-testid="kpi-card">
        <span style="font-size:12px;color:var(--muted)">{{ m.label }}</span>
        <strong style="font-size:22px;display:block">{{ m.value }}</strong>
        <span style="font-size:12px;color:var(--muted)">{{ m.hint }}</span>
      </article>
    </div>

    <div class="board-toolbar">
      <div class="board-tabs">
        <button
          class="tab"
          :class="{ active: viewMode === 'overview' }"
          type="button"
          data-testid="tab-overview"
          @click="viewMode = 'overview'"
        >
          概览视图
        </button>
        <button
          class="tab"
          :class="{ active: viewMode === 'detail' }"
          type="button"
          data-testid="tab-detail"
          @click="viewMode = 'detail'"
        >
          明细视图
        </button>
      </div>
      <span class="board-hint">
        已发布 {{ publishedSnapshots.length }} 份 · 共 {{ snapshots.length }} 份看板聚合快照
      </span>
    </div>

    <p v-if="errorMessage" class="error-text" data-testid="board-error">{{ errorMessage }}</p>

    <div v-if="verification" class="verify-box" data-testid="verification-result">
      <strong>核对结论：{{ verification.留档.结论 }}</strong>
      <span class="board-hint">（快照 {{ verification.留档.快照编号 }}，已按 V003 留档）</span>
      <p v-for="step in verification.校验" :key="step.步骤" class="snapshot-meta">
        {{ step.通过 ? '✓' : '✗' }} {{ step.步骤 }} — {{ step.说明 }}
      </p>
    </div>

    <!-- 概览视图：每份快照独立排列，卡片按指标展示 -->
    <div v-if="viewMode === 'overview'" class="snapshot-grid" data-testid="snapshot-overview">
      <article
        v-for="snapshot in snapshots"
        :key="snapshot.id"
        class="snapshot-panel"
        :data-testid="`snapshot-${snapshot.id}`"
        :data-published="snapshot.是否发布 ? 'true' : 'false'"
      >
        <header class="snapshot-head">
          <div>
            <strong>{{ snapshot.看板名称 }}</strong>
            <span class="snapshot-code">{{ snapshot.快照编号 }}</span>
          </div>
          <span class="status-badge" :class="`status-${snapshot.状态}`">{{ snapshot.状态 }}</span>
        </header>
        <p class="snapshot-meta">
          口径模式：{{ snapshot.口径模式 }} · 覆盖实验 {{ snapshot.覆盖实验数 }} 个 ·
          卡片 {{ snapshot.卡片数 }} 张 ·
          未完成实验 {{ (snapshot.未完成实验 || []).join('、') || '无' }}
        </p>
        <p v-if="snapshot.失败原因" class="error-text">失败原因：{{ snapshot.失败原因 }}</p>
        <p v-if="snapshot.上一完整快照编号" class="snapshot-meta">
          失败时保留上一完整快照：{{ snapshot.上一完整快照编号 }}
        </p>

        <div class="card-grid">
          <button
            v-for="card in snapshot.卡片"
            :key="card.卡片编号"
            class="metric-card"
            type="button"
            :class="{ active: expandedKey === `${snapshot.id}-${card.id}` }"
            :data-testid="`card-${snapshot.id}-${card.id}`"
            @click="toggleCard(snapshot, card)"
          >
            <span class="metric-name">{{ card.指标名称 }}</span>
            <strong class="metric-value">{{ card.指标值 }}</strong>
            <span class="metric-diff" :class="card.差异 >= 0 ? 'trend-up' : 'trend-down'">
              较基准 {{ card.差异 >= 0 ? '+' : '' }}{{ card.差异 }}
            </span>
            <span class="caliber-line" :data-testid="`card-caliber-${snapshot.id}-${card.id}`">
              口径 {{ card.口径版本 }} · {{ card.口径版本编号 }}
            </span>
            <span v-if="card.口径冲突" class="conflict-badge">
              源口径 {{ card.冲突版本.join(' / ') }} → 统一 {{ card.口径版本 }}
            </span>
            <span class="metric-source">{{ card.数据来源 }} · 实验 {{ card.样本实验数 }} 个</span>
          </button>
          <p v-if="!snapshot.卡片.length" class="empty-state">该快照暂无已发布卡片</p>
        </div>

        <div v-if="expandedCard && expandedCard.snapshotId === snapshot.id" class="card-expand" data-testid="card-expand">
          <div class="card-expand-head">
            <strong>{{ expandedCard.card.指标名称 }} · 实验快照</strong>
            <span>{{ expandedCard.card.处理方式 }}</span>
          </div>
          <p v-if="expandedCard.card.实验差异说明?.length" class="snapshot-meta">
            实验差异说明：{{ expandedCard.card.实验差异说明.join('；') }}
          </p>
          <table class="data-table">
            <thead>
              <tr>
                <th>实验编号</th><th>来源</th><th>周期</th><th>源口径</th><th>统一口径</th>
                <th>换算系数</th><th>对照/实验原值</th><th>对照/实验统一值</th><th>差异</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in expandedCard.rows" :key="row.id" :data-testid="`exp-row-${row.id}`">
                <td>{{ row.实验编号 }}</td>
                <td>{{ row.来源 }}</td>
                <td>{{ row.周期 }}</td>
                <td>{{ row.源口径版本 }}</td>
                <td>{{ row.统一口径版本 }}</td>
                <td>{{ row.换算系数 }}</td>
                <td>{{ row.对照组原值 }} / {{ row.实验组原值 }}</td>
                <td>{{ row.对照组统一值 }} / {{ row.实验组统一值 }}</td>
                <td>{{ row.差异 }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <footer v-if="!snapshot.是否发布" class="snapshot-actions">
          <button class="link" type="button" :data-testid="`recover-${snapshot.id}`" @click="recoverSnapshot(snapshot)">
            按未完成实验续写
          </button>
          <button class="link" type="button" :data-testid="`rollback-${snapshot.id}`" @click="rollbackSnapshot(snapshot)">
            回滚未发布快照
          </button>
        </footer>
      </article>
    </div>

    <!-- 明细视图：同一份快照视图的列表入口，点击详情打开详情面板 -->
    <div v-else class="snapshot-table-wrap" data-testid="snapshot-detail">
      <table class="data-table">
        <thead>
          <tr>
            <th>快照编号</th><th>看板</th><th>状态</th><th>是否发布</th><th>卡片数</th>
            <th>覆盖实验</th><th>未完成实验</th><th>生成时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="snapshot in snapshots"
            :key="snapshot.id"
            :data-testid="`snapshot-row-${snapshot.id}`"
            :data-status="snapshot.状态"
          >
            <td>{{ snapshot.快照编号 }}</td>
            <td>{{ snapshot.看板名称 }}</td>
            <td>{{ snapshot.状态 }}</td>
            <td>{{ snapshot.是否发布 ? '已发布' : '未发布' }}</td>
            <td>{{ snapshot.卡片数 }}</td>
            <td>{{ (snapshot.实验范围 || []).join('、') }}</td>
            <td>{{ (snapshot.未完成实验 || []).join('、') || '—' }}</td>
            <td>{{ snapshot.生成时间 }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`open-detail-${snapshot.id}`" @click="openDetail(snapshot)">
                查看详情
              </button>
            </td>
          </tr>
          <tr v-if="!snapshots.length">
            <td colspan="9" class="empty-state">暂无看板聚合快照，可先刷新看板快照</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 详情面板：与列表入口使用同一份快照视图，字段与卡片完全一致 -->
    <div v-if="detailSnapshot" class="modal-backdrop" data-testid="snapshot-detail-panel">
      <section class="modal detail-panel">
        <header class="page-head">
          <div>
            <h3>{{ detailSnapshot.快照编号 }}</h3>
            <p class="page-desc">
              {{ detailSnapshot.看板名称 }} · {{ detailSnapshot.状态 }} ·
              {{ detailSnapshot.是否发布 ? '已发布' : '未发布' }} · 口径模式 {{ detailSnapshot.口径模式 }}
            </p>
          </div>
          <button class="btn" type="button" data-testid="close-detail" @click="detailSnapshot = null">关闭</button>
        </header>
        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">卡片数</span><strong class="stat-value">{{ detailSnapshot.卡片数 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">已绑定口径</span
            ><strong class="stat-value">{{ detailSnapshot.已绑定口径数 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">覆盖实验</span
            ><strong class="stat-value">{{ detailSnapshot.覆盖实验数 }}</strong>
          </article>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>指标</th><th>指标值</th><th>对比基准</th><th>差异</th><th>口径版本</th>
              <th>口径版本编号</th><th>处理方式</th><th>实验数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="card in detailSnapshot.卡片" :key="card.卡片编号">
              <td>{{ card.指标名称 }}（{{ card.指标编码 }}）</td>
              <td>{{ card.指标值 }}</td>
              <td>{{ card.对比基准 }}</td>
              <td>{{ card.差异 }}</td>
              <td>{{ card.口径版本 }}</td>
              <td>{{ card.口径版本编号 }}</td>
              <td>{{ card.处理方式 }}</td>
              <td>{{ card.样本实验数 }}</td>
            </tr>
            <tr v-if="!detailSnapshot.卡片.length">
              <td colspan="8" class="empty-state">该快照没有卡片</td>
            </tr>
          </tbody>
        </table>
        <h4 style="margin:16px 0 8px">按实验展开的实验快照</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>实验编号</th><th>指标</th><th>来源</th><th>周期</th><th>源口径</th>
              <th>统一口径</th><th>对照/实验统一值</th><th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in detailSnapshot.实验快照 || []" :key="row.id">
              <td>{{ row.实验编号 }}</td>
              <td>{{ row.指标编码 }}</td>
              <td>{{ row.来源 }}</td>
              <td>{{ row.周期 }}</td>
              <td>{{ row.源口径版本 }}</td>
              <td>{{ row.统一口径版本 }}</td>
              <td>{{ row.对照组统一值 }} / {{ row.实验组统一值 }}</td>
              <td>{{ row.说明 }}</td>
            </tr>
            <tr v-if="!(detailSnapshot.实验快照 || []).length">
              <td colspan="8" class="empty-state">该快照没有实验快照行</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <form class="analysis-form" @submit.prevent="runAnalysis">
      <label>
        <span>看板编号</span>
        <select v-model="selectedBoard" data-testid="board-select">
          <option v-for="board in boards" :key="board.看板编号" :value="board.看板编号">
            {{ board.看板编号 }} · {{ board.看板名称 }}
          </option>
        </select>
      </label>
      <label>
        <span>模拟失败实验</span>
        <input v-model="failExperiments" placeholder="例如 EXPE-0002，留空表示全部成功" />
      </label>
      <button class="btn primary" type="submit" data-testid="run-analysis">运行分析</button>
      <span class="board-hint">运行分析 = 按看板配置重新聚合一次快照</span>
    </form>

    <div v-if="chartData.length" class="analysis-chart">
      <div
        v-for="(bar, index) in chartData"
        :key="index"
        class="analysis-bar"
        :style="{ height: barHeight(bar.value) + 'px' }"
      >
        <span>{{ bar.label }}</span>
      </div>
    </div>

    <table class="data-table" v-if="results.length">
      <thead>
        <tr><th>指标编码</th><th>指标名称</th><th>指标值</th><th>口径版本</th><th>口径版本编号</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in results" :key="row.指标编码">
          <td>{{ row.指标编码 }}</td>
          <td>{{ row.指标名称 }}</td>
          <td>{{ row.指标值 }}</td>
          <td>{{ row.口径版本 }}</td>
          <td>{{ row.口径版本编号 }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!results.length && !loading" style="text-align:center;color:var(--muted)">
      选择看板后运行分析，生成看板聚合快照
    </p>

    <footer class="page-foot">
      <span>共 {{ snapshots.length }} 份看板聚合快照，{{ publishedSnapshots.length }} 份已发布</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type SnapshotRow = Record<string, any>
type ExperimentRow = Record<string, any>
type Card = Record<string, any> & { 实验快照?: ExperimentRow[] }

const ENDPOINT = '/api/evaluate_board'

const snapshots = ref<SnapshotRow[]>([])
const boards = ref<Record<string, any>[]>([])
const summary = ref<Record<string, number>>({ 看板快照: 0, 聚合卡片: 0, 已发布口径: 0, 覆盖实验: 0 })
const viewMode = ref<'overview' | 'detail'>('overview')
const detailSnapshot = ref<SnapshotRow | null>(null)
const expandedCard = ref<{ snapshotId: number; card: Card; rows: ExperimentRow[] } | null>(null)
const expandedKey = ref('')
const selectedBoard = ref('')
const failExperiments = ref('')
const results = ref<Card[]>([])
const chartData = ref<{ label: string; value: number }[]>([])
const loading = ref(false)
const errorMessage = ref('')
const verification = ref<Record<string, any> | null>(null)
const currentSnapshotId = ref<number | null>(null)

const publishedSnapshots = computed(() => snapshots.value.filter((item) => item.是否发布))
const summaryMetrics = computed(() => [
  { label: '看板快照', value: summary.value.看板快照 ?? snapshots.value.length, hint: '含失败未发布快照' },
  { label: '聚合卡片', value: summary.value.聚合卡片 ?? 0, hint: '已发布快照内卡片' },
  { label: '已发布口径', value: summary.value.已发布口径 ?? 0, hint: '每卡仅引用一个登记口径' },
  { label: '覆盖实验', value: summary.value.覆盖实验 ?? 0, hint: '快照聚合到的实验数' },
])

function barHeight(value: number) {
  const max = Math.max(...chartData.value.map((item) => item.value), 1)
  return Math.max(10, (value / max) * 140)
}

async function reload() {
  // 不在重载时清空错误：动作失败的原因需要在列表刷新后仍然可见。
  try {
    const [snapshotPayload, boardPayload, summaryPayload] = await Promise.all([
      fetchJson<{ items: SnapshotRow[] }>(`${ENDPOINT}/snapshots`),
      fetchJson<{ items: Record<string, any>[] }>(ENDPOINT),
      fetchJson<{ metrics: { label: string; value: number }[] }>(`${ENDPOINT}/summary`),
    ])
    snapshots.value = snapshotPayload.items ?? []
    boards.value = boardPayload.items ?? []
    summary.value = Object.fromEntries((summaryPayload.metrics ?? []).map((item) => [item.label, item.value]))
    if (!selectedBoard.value && boards.value.length) selectedBoard.value = String(boards.value[0].看板编号)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '看板聚合快照读取失败'
  }
}

async function toggleCard(snapshot: SnapshotRow, card: Card) {
  const key = `${snapshot.id}-${card.id}`
  if (expandedKey.value === key) {
    expandedKey.value = ''
    expandedCard.value = null
    return
  }
  try {
    const detail = await fetchJson<Card>(`${ENDPOINT}/snapshots/${snapshot.id}/cards/${card.id}`)
    expandedCard.value = { snapshotId: snapshot.id, card: detail, rows: detail.实验快照 ?? [] }
    expandedKey.value = key
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '实验快照展开失败'
  }
}

async function openDetail(snapshot: SnapshotRow) {
  // 详情面板复用列表入口的同一份快照视图，只额外拉一次最新数据。
  detailSnapshot.value = snapshot
  currentSnapshotId.value = snapshot.id
  verification.value = null
  try {
    detailSnapshot.value = await fetchJson<SnapshotRow>(`${ENDPOINT}/snapshots/${snapshot.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照详情读取失败'
  }
}

function failList(): string[] {
  return failExperiments.value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

async function refreshAll() {
  loading.value = true
  errorMessage.value = ''
  verification.value = null
  try {
    const response = await request(`${ENDPOINT}/snapshots/refresh`, {
      method: 'POST',
      body: JSON.stringify({ board_code: selectedBoard.value || null, fail_experiments: failList() }),
    })
    const payload = await response.json()
    if (!payload.ok) errorMessage.value = payload.message || '快照刷新失败'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照刷新失败'
  } finally {
    loading.value = false
  }
}

async function recoverSnapshot(snapshot: SnapshotRow) {
  try {
    const response = await request(`${ENDPOINT}/snapshots/${snapshot.id}/recover`, {
      method: 'POST',
      body: JSON.stringify({ fail_experiments: failList() }),
    })
    const payload = await response.json()
    if (!payload.已发布) errorMessage.value = payload.消息 || '续写未完成'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照续写失败'
  }
}

async function rollbackSnapshot(snapshot: SnapshotRow) {
  try {
    const response = await request(`${ENDPOINT}/snapshots/${snapshot.id}/rollback`, { method: 'POST' })
    const payload = await response.json()
    if (!payload.ok) errorMessage.value = payload.message || '回滚失败'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照回滚失败'
  }
}

async function verifyCurrent() {
  const target = currentSnapshotId.value ?? snapshots.value[0]?.id
  if (!target) {
    errorMessage.value = '还没有可核对的看板聚合快照'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/snapshots/${target}/verify`, { method: 'POST' })
    const payload = await response.json()
    verification.value = payload
    if (payload.快照) {
      snapshots.value = snapshots.value.map((item) => (item.id === target ? payload.快照 : item))
      if (detailSnapshot.value?.id === target) detailSnapshot.value = payload.快照
    }
    if (!payload.ok) errorMessage.value = payload.message || '核对未通过'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照核对失败'
  }
}

async function runAnalysis() {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/run`, {
      method: 'POST',
      body: JSON.stringify({ values: { 看板编号: selectedBoard.value, fail_experiments: failExperiments.value } }),
    })
    const payload = await response.json()
    const batch: SnapshotRow[] = payload.items ?? []
    const latest = batch.find((item) => item.看板编号 === selectedBoard.value) ?? batch[0]
    results.value = latest?.卡片 ?? []
    chartData.value = results.value.map((card) => ({ label: card.指标编码, value: Number(card.指标值) || 0 }))
    if (latest && latest.状态 === '失败') errorMessage.value = latest.失败原因 || '快照生成失败'
    await reload()
  } catch (error) {
    results.value = []
    errorMessage.value = error instanceof Error ? error.message : '聚合失败'
  } finally {
    loading.value = false
  }
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

onMounted(reload)
</script>

<style scoped>
.board-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 12px 0;
}
.board-tabs {
  display: flex;
  gap: 8px;
}
.tab {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 6px;
  padding: 6px 14px;
  cursor: pointer;
}
.tab.active {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.board-hint {
  font-size: 12px;
  color: var(--muted);
}
.snapshot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 14px;
}
.snapshot-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
}
.snapshot-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}
.snapshot-code {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}
.snapshot-meta {
  font-size: 12px;
  color: var(--muted);
  margin: 6px 0;
}
.status-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef2f7;
}
.status-badge.status-已完成 {
  background: #dcfce7;
  color: #15803d;
}
.status-badge.status-失败 {
  background: #fee2e2;
  color: #b91c1c;
}
.status-badge.status-已回滚 {
  background: #fef3c7;
  color: #92400e;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-top: 10px;
}
.metric-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  background: #fafbfc;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
}
.metric-card.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 2px rgb(31 111 235 / 15%);
}
.metric-name {
  font-size: 13px;
  color: var(--muted);
}
.metric-value {
  font-size: 20px;
}
.metric-diff {
  font-size: 12px;
}
.trend-up {
  color: #16a34a;
}
.trend-down {
  color: #dc2626;
}
.caliber-line {
  font-size: 12px;
  color: #1d4ed8;
}
.conflict-badge {
  font-size: 11px;
  color: #92400e;
  background: #fef3c7;
  border-radius: 4px;
  padding: 2px 6px;
}
.metric-source {
  font-size: 11px;
  color: var(--muted);
}
.card-expand {
  margin-top: 12px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.card-expand-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 6px;
}
.snapshot-actions {
  display: flex;
  gap: 12px;
  margin-top: 10px;
}
.detail-panel {
  width: min(980px, 100%);
}
.verify-box {
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #f8fafc;
}
</style>
