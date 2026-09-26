<template>
  <section class="page" data-module="pothole">
    <header class="page-head">
      <div>
        <h2>坑槽修补管理</h2>
        <p class="page-desc">维护修补单，围绕修补单号、所在路段、修补面积、修补材料做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记修补单</button>
        <button class="btn" type="button" @click="exportRows">导出坑槽修补清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ formatNumber(item.value) }}<small class="stat-unit">{{ item.unit }}</small></strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>修补单号</span>
        <input v-model="keyword" placeholder="按修补单号检索" />
      </label>
      <label class="filter-item">
        <span>修补状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '修补单号'" class="link" type="button" @click="openDetail(Number(row.id))">
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(String(row.status))"
              :key="action"
              class="link"
              type="button"
              :disabled="busyId === row.id"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="rows.length">
          <td :colspan="areaColumnIndex">合计（当前筛选）</td>
          <td>{{ formatNumber(summary['修补面积合计']) }}</td>
          <td></td>
          <td>{{ formatNumber(summary['用料数量合计']) }}</td>
          <td :colspan="columns.length - materialColumnIndex"></td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的坑槽修补数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条坑槽修补记录（合计与上方明细同口径）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="detail-mask" @click.self="closeDetail">
      <div class="detail-panel" role="dialog" aria-modal="true" aria-label="修补单详情">
        <header class="detail-head">
          <h3>修补单详情 · {{ detail['修补单号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <p class="detail-status">当前状态：<strong>{{ detail.status }}</strong></p>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field.key">
            <dt>{{ field.key }}</dt>
            <dd>
              <input
                v-if="field.editable"
                v-model="detailForm[field.key]"
                :type="field.numeric ? 'number' : 'text'"
                :step="field.numeric ? '0.01' : undefined"
                :min="field.numeric ? 0 : undefined"
              />
              <span v-else>{{ detail[field.key] || '—' }}</span>
            </dd>
          </template>
        </dl>
        <p v-if="detailMessage" class="detail-message" :class="{ 'error-text': !detailOk }">{{ detailMessage }}</p>
        <footer class="detail-foot">
          <button class="btn primary" type="button" :disabled="detailBusy" @click="saveResult">保存结果</button>
          <button
            v-for="action in availableActions(String(detail.status))"
            :key="action"
            class="btn"
            type="button"
            :disabled="detailBusy"
            @click="runAction(action)"
          >
            {{ action }}
          </button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: number; unit: string }
type DetailField = { key: string; editable: boolean; numeric: boolean }

const ENDPOINT = '/api/pothole'
const columns = ["修补单号", "所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期", "修补状态"]
const statuses = ["待安排", "修补中", "已完成", "已取消"]
const areaColumnIndex = columns.indexOf("修补面积")
const materialColumnIndex = columns.indexOf("用料数量")
const NUMERIC_KEYS = ["修补面积", "用料数量"]
const EDITABLE_KEYS = ["所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期"]
const READONLY_KEYS = ["修补单号", "修补状态"]

const ACTIONS_BY_STATUS: Record<string, string[]> = {
  "待安排": ["安排修补", "取消修补"],
  "修补中": ["确认完成", "取消修补"],
  "已完成": [],
  "已取消": [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const statCards = ref<StatCard[]>([
  { label: '待安排修补', value: 0, unit: '单' },
  { label: '本月修补面积', value: 0, unit: '㎡' },
  { label: '取消单数', value: 0, unit: '单' },
])
const summary = ref<Record<string, number>>({})

const detail = ref<Row | null>(null)
const detailForm = ref<Record<string, string>>({})
const detailBusy = ref(false)
const detailMessage = ref('')
const detailOk = ref(true)
const busyId = ref<number | null>(null)

const detailFields: DetailField[] = [...READONLY_KEYS, ...EDITABLE_KEYS].map((key) => ({
  key,
  editable: EDITABLE_KEYS.includes(key),
  numeric: NUMERIC_KEYS.includes(key),
}))

function availableActions(status: string): string[] {
  return ACTIONS_BY_STATUS[status] ?? []
}

function formatNumber(value: number | null | undefined): string {
  const number = Number(value ?? 0)
  return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '修补单登记入口尚未接入审批流'
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (keyword.value.trim()) {
    params.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    params.set('status', statusFilter.value)
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}

async function reload() {
  errorMessage.value = ''
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}${buildQuery()}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok) {
      throw new Error('修补单列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    summary.value = payload.summary ?? {}
    if (statsResponse.ok) {
      const statsPayload = await statsResponse.json()
      statCards.value = statsPayload.cards ?? statCards.value
    }
    if (detail.value) {
      const latest = rows.value.find((row) => String(row.id) === String(detail.value?.id))
      if (latest) {
        detail.value = latest
        detailForm.value = Object.fromEntries(
          EDITABLE_KEYS.map((key) => [key, latest[key] == null ? '' : String(latest[key])]),
        )
      } else {
        await refreshDetail(Number(detail.value.id))
      }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '坑槽修补列表读取失败'
  }
}

async function openDetail(id: number) {
  errorMessage.value = ''
  detailMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail ?? '修补单详情读取失败')
    }
    detail.value = payload
    detailForm.value = Object.fromEntries(
      EDITABLE_KEYS.map((key) => [key, payload[key] == null ? '' : String(payload[key])]),
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '修补单详情读取失败'
  }
}

async function refreshDetail(id: number) {
  const response = await request(`${ENDPOINT}/${id}`)
  if (!response.ok) {
    detail.value = null
    return
  }
  detail.value = await response.json()
  detailForm.value = Object.fromEntries(
    EDITABLE_KEYS.map((key) => [
      key,
      detail.value?.[key] == null ? '' : String(detail.value[key]),
    ]),
  )
}

function closeDetail() {
  if (detailBusy.value) {
    return
  }
  detail.value = null
  detailMessage.value = ''
}

function formValues(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(detailForm.value).map(([key, value]) => [key, String(value).trim()]),
  )
}

async function saveResult() {
  if (!detail.value || detailBusy.value) {
    return
  }
  detailBusy.value = true
  detailMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${detail.value.id}/result`, {
      method: 'PUT',
      body: JSON.stringify({ values: formValues() }),
    })
    const payload = await response.json()
    detailOk.value = Boolean(payload.ok)
    detailMessage.value = payload.message || (payload.ok ? '修补结果已保存' : '修补结果未生效')
    if (payload.ok) {
      await reload()
    }
  } catch (error) {
    detailOk.value = false
    detailMessage.value = error instanceof Error ? error.message : '修补结果保存失败'
  } finally {
    detailBusy.value = false
  }
}

async function runAction(action: string, row?: Row) {
  const target = row ? row : detail.value
  if (!target) {
    return
  }
  const targetId = Number(target.id)
  if (row && busyId.value === targetId) {
    return
  }
  if (!row) {
    detailBusy.value = true
  } else {
    busyId.value = targetId
  }
  errorMessage.value = ''
  detailMessage.value = ''
  const body: Record<string, unknown> = { action }
  // 详情页确认完成时把当前表单整体提交：清空面积或把用料改成负数会被后端拦下，
  // 已生效的原值不受影响；列表行的动作不附带表单。
  if (!row && action === '确认完成') {
    Object.assign(body, formValues())
  }
  try {
    const response = await request(`${ENDPOINT}/${targetId}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: body }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      const message = payload.message || '坑槽修补动作未生效，请稍后重试'
      if (row) {
        errorMessage.value = message
      } else {
        detailOk.value = false
        detailMessage.value = message
      }
      return
    }
    if (!row) {
      detailOk.value = true
      detailMessage.value = payload.message
    }
    await reload()
  } catch (error) {
    const message = error instanceof Error ? error.message : '坑槽修补操作失败'
    if (row) {
      errorMessage.value = message
    } else {
      detailOk.value = false
      detailMessage.value = message
    }
  } finally {
    busyId.value = null
    detailBusy.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.stat-unit {
  margin-left: 4px;
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}
.filter-item select {
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
}
.detail-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.detail-panel {
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: 86vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px 18px;
}
.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.detail-head h3 {
  margin: 0;
  font-size: 16px;
}
.detail-status {
  margin: 8px 0 12px;
  font-size: 13px;
  color: var(--muted);
}
.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px 12px;
  margin: 0 0 12px;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
}
.detail-grid input {
  width: 100%;
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
}
.detail-message {
  font-size: 12px;
  margin: 0 0 8px;
}
.detail-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
