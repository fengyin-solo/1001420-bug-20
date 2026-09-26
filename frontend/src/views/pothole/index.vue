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
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
            <button v-if="column === '修补单号'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无坑槽修补数据，可先登记修补单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>
        共 {{ total }} 条坑槽修补记录 ｜ 修补面积合计 {{ totals['修补面积合计'] ?? 0 }} ｜ 用料数量合计 {{ totals['用料数量合计'] ?? 0 }}
      </span>
      <span v-if="notice" class="notice-text">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="drawer-mask" @click.self="closeDetail">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>修补单详情 {{ detail['修补单号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>
              <input
                v-if="editableFields.includes(column)"
                v-model="edits[column]"
                :placeholder="`请输入${column}`"
              />
              <template v-else>{{ detail[column] ?? '—' }}</template>
            </dd>
          </template>
        </dl>
        <p class="drawer-tip">修补面积、用料数量、完成日期可随「确认完成」一起提交；不合规的提交不会生效，原值保留。</p>
        <div class="drawer-actions">
          <button
            v-for="action in actions"
            :key="action"
            class="btn"
            type="button"
            @click="runAction(action, detail, edits)"
          >
            {{ action }}
          </button>
        </div>
        <p v-if="detailNotice" class="drawer-message ok">{{ detailNotice }}</p>
        <p v-if="detailMessage" class="drawer-message">{{ detailMessage }}</p>
      </aside>
    </div>

    <div v-if="createVisible" class="drawer-mask" @click.self="createVisible = false">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>登记修补单</h3>
          <button class="btn ghost" type="button" @click="createVisible = false">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="field in createFields" :key="field">
            <dt>{{ field }}<span v-if="requiredFields.includes(field)">（必填）</span></dt>
            <dd><input v-model="createForm[field]" :placeholder="`请输入${field}`" /></dd>
          </template>
        </dl>
        <div class="drawer-actions">
          <button class="btn primary" type="button" @click="submitCreate">提交登记</button>
        </div>
        <p v-if="createMessage" class="drawer-message">{{ createMessage }}</p>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/pothole'
const columns = ["修补单号", "所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期", "修补状态"]
const actions = ["安排修补", "确认完成", "取消修补"]
const editableFields = ["修补面积", "用料数量", "完成日期"]
const createFields = ["修补单号", "所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期"]
const requiredFields = ["修补单号", "所在路段", "修补面积"]

const stats = ref([{ label: '待安排修补', value: 0 }, { label: '本月修补面积', value: 0 }, { label: '取消单数', value: 0 }])
const totals = ref<Record<string, number>>({})
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const notice = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const detail = ref<Row | null>(null)
const edits = ref<Record<string, string>>({})
const detailMessage = ref('')
const detailNotice = ref('')
const createVisible = ref(false)
const createForm = ref<Record<string, string>>({})
const createMessage = ref('')

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  createMessage.value = ''
  createVisible.value = true
}

async function submitCreate() {
  createMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createMessage.value = payload?.message ?? payload?.detail ?? '修补单登记未生效'
      return
    }
    createVisible.value = false
    notice.value = payload.message ?? '修补单已登记'
    await reload()
  } catch (error) {
    createMessage.value = error instanceof Error ? error.message : '修补单登记失败'
  }
}

async function openDetail(row: Row) {
  detailMessage.value = ''
  detailNotice.value = ''
  edits.value = {}
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('修补单详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '修补单详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
  detailMessage.value = ''
  detailNotice.value = ''
}

async function runAction(action: string, row: Row, extra?: Record<string, string>) {
  errorMessage.value = ''
  notice.value = ''
  detailMessage.value = ''
  detailNotice.value = ''
  const values: Record<string, unknown> = { action }
  if (extra) {
    for (const [key, value] of Object.entries(extra)) {
      if (value !== undefined && value !== null && String(value).trim() !== '') {
        values[key] = value
      }
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      const message = payload?.message ?? payload?.detail ?? '坑槽修补动作未生效，请稍后重试'
      if (detail.value) {
        detailMessage.value = message
      } else {
        errorMessage.value = message
      }
      return
    }
    notice.value = payload.message ?? `修补单已${action}`
    await reload()
    if (detail.value) {
      detailNotice.value = notice.value
      edits.value = {}
      const refreshed = await request(`${ENDPOINT}/${row.id}`)
      if (refreshed.ok) {
        detail.value = await refreshed.json()
      }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '坑槽修补操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('修补单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (Array.isArray(payload.cards) && payload.cards.length) {
      stats.value = payload.cards
    }
    totals.value = payload.totals ?? {}
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '坑槽修补列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  justify-content: flex-end;
  z-index: 20;
}
.drawer {
  width: 380px;
  max-width: 90vw;
  background: #fff;
  padding: 16px;
  overflow-y: auto;
  box-shadow: -4px 0 16px rgba(15, 23, 42, 0.12);
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.drawer-head h3 {
  margin: 0;
  font-size: 15px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px 10px;
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
.drawer-tip {
  font-size: 12px;
  color: var(--muted);
}
.drawer-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.drawer-message {
  margin-top: 10px;
  font-size: 12px;
  color: #b42318;
}
.drawer-message.ok {
  color: #067647;
}
.notice-text {
  color: #067647;
}
</style>
