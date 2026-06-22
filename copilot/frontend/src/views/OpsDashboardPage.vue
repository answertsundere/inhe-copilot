<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createEvalRun,
  getEvalFailures,
  getEvalRepairTasks,
  getEvalRunDetail,
  getEvalRuns,
  getModelCalls,
  getModelSummary,
  getToolCalls,
  getToolSummary,
} from '../api/ops'

const activeTab = ref('models')
const loading = reactive({ summary: false, models: false, tools: false, evals: false, repairs: false })
const errorMessage = ref('')
const selectedRun = ref<any>(null)

const modelSummary = ref<any>({})
const toolSummary = ref<any>({})
const evalRuns = ref<any[]>([])
const modelCalls = ref<any[]>([])
const toolCalls = ref<any[]>([])
const evalFailures = ref<any[]>([])
const repairTasks = ref<any[]>([])

const modelFilters = reactive({ alias: '', node_name: '', status: '', since: '' })
const toolFilters = reactive({ tool_name: '', status: '', allowed: '', intent: '' })

const currentRole = computed(() => localStorage.getItem('kb_user_role') || 'supervisor')
const isForbidden = computed(() => errorMessage.value.includes('forbidden') || errorMessage.value.includes('403'))
const latestEvalFailed = computed(() => evalRuns.value[0]?.failed_cases ?? 0)
const cards = computed(() => [
  { label: '今日模型调用', value: modelSummary.value.total_calls ?? 0, tone: 'primary' },
  { label: '今日模型失败', value: modelSummary.value.error_calls ?? 0, tone: 'danger' },
  { label: '今日工具 blocked', value: toolSummary.value.blocked_calls ?? 0, tone: 'warning' },
  { label: '最新 eval 失败', value: latestEvalFailed.value, tone: latestEvalFailed.value > 0 ? 'danger' : 'success' },
])

function todayStart() {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

async function loadAll() {
  errorMessage.value = ''
  await Promise.all([loadSummary(), loadModelCalls(), loadToolCalls(), loadEvalRuns(), loadRepairs()])
}

async function loadSummary() {
  loading.summary = true
  try {
    const params = { since: todayStart() }
    const [model, tool] = await Promise.all([getModelSummary(params), getToolSummary(params)])
    modelSummary.value = model.data || {}
    toolSummary.value = tool.data || {}
  } catch (e: any) { handleError(e) } finally { loading.summary = false }
}

async function loadModelCalls() {
  loading.models = true
  try {
    const { data } = await getModelCalls(cleanParams({ ...modelFilters, limit: 50 }))
    modelCalls.value = data.items || []
  } catch (e: any) { handleError(e) } finally { loading.models = false }
}

async function loadToolCalls() {
  loading.tools = true
  try {
    const { data } = await getToolCalls(cleanParams({ ...toolFilters, limit: 50 }))
    toolCalls.value = data.items || []
  } catch (e: any) { handleError(e) } finally { loading.tools = false }
}

async function loadEvalRuns() {
  loading.evals = true
  try {
    const [runs, failures] = await Promise.all([getEvalRuns({ limit: 50 }), getEvalFailures({ limit: 50 })])
    evalRuns.value = runs.data.items || []
    evalFailures.value = failures.data.items || []
  } catch (e: any) { handleError(e) } finally { loading.evals = false }
}

async function loadRepairs() {
  loading.repairs = true
  try {
    const { data } = await getEvalRepairTasks({ limit: 50 })
    repairTasks.value = data.items || []
  } catch (e: any) { handleError(e) } finally { loading.repairs = false }
}

async function openRunDetail(row: any) {
  try {
    const { data } = await getEvalRunDetail(row.run_uid)
    selectedRun.value = data
  } catch (e: any) { handleError(e) }
}

async function runDryEval() {
  try {
    const { data } = await createEvalRun({ limit: 10, apply: false, run_type: 'manual' })
    ElMessage.success(`Dry-run 完成：${data.total_cases ?? 0} 条`)
  } catch (e: any) { handleError(e) }
}

async function runApplyEval() {
  try {
    await ElMessageBox.confirm('确认执行 apply 回放？这会写入 eval_runs、traces 和 failures。', '二次确认', { type: 'warning' })
    const { data } = await createEvalRun({ limit: 10, apply: true, run_type: 'manual' })
    ElMessage.success(`回放完成：失败 ${data.run?.failed_cases ?? 0} 条`)
    await Promise.all([loadEvalRuns(), loadRepairs(), loadSummary()])
  } catch (e: any) {
    if (e !== 'cancel') handleError(e)
  }
}

function cleanParams(params: Record<string, any>) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined))
}

function handleError(e: any) {
  const status = e?.response?.status
  const code = e?.response?.data?.error || e?.message || '请求失败'
  errorMessage.value = status ? `${status}: ${code}` : code
  ElMessage.error(errorMessage.value)
}

function formatCost(row: any) {
  return `${Number(row.estimated_cost || 0).toFixed(6)} ${row.currency || ''}`.trim()
}

function formatJsonList(value: any) {
  return Array.isArray(value) ? value.join(', ') : ''
}

onMounted(loadAll)
</script>

<template>
  <div class="ops-page">
    <el-alert
      v-if="isForbidden"
      title="当前角色无权访问运营监控"
      type="warning"
      :description="`当前角色：${currentRole}。请切换为 supervisor 或 admin。`"
      show-icon
      :closable="false"
    />

    <div class="summary-grid" v-loading="loading.summary">
      <div v-for="card in cards" :key="card.label" class="metric-card">
        <div class="metric-label">{{ card.label }}</div>
        <div :class="['metric-value', card.tone]">{{ card.value }}</div>
      </div>
    </div>

    <el-card shadow="never" class="ops-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="模型调用" name="models">
          <div class="filter-row">
            <el-input v-model="modelFilters.alias" placeholder="alias" clearable />
            <el-input v-model="modelFilters.node_name" placeholder="node_name" clearable />
            <el-select v-model="modelFilters.status" placeholder="status" clearable>
              <el-option label="success" value="success" />
              <el-option label="error" value="error" />
            </el-select>
            <el-date-picker v-model="modelFilters.since" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="since" />
            <el-button type="primary" @click="loadModelCalls">筛选</el-button>
          </div>
          <el-table :data="modelCalls" v-loading="loading.models" height="520" empty-text="暂无模型调用">
            <el-table-column prop="created_at" label="时间" min-width="170" show-overflow-tooltip />
            <el-table-column prop="alias" label="alias" width="120" />
            <el-table-column prop="node_name" label="node_name" min-width="150" show-overflow-tooltip />
            <el-table-column prop="status" label="status" width="100">
              <template #default="{ row }"><el-tag :type="row.status === 'error' ? 'danger' : 'success'" size="small">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="tokens" width="100"><template #default="{ row }">{{ row.total_tokens }}</template></el-table-column>
            <el-table-column label="cost" width="130"><template #default="{ row }">{{ formatCost(row) }}</template></el-table-column>
            <el-table-column prop="latency_ms" label="latency" width="100" />
            <el-table-column prop="error_type" label="error_type" min-width="130" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="工具调用" name="tools">
          <div class="filter-row">
            <el-input v-model="toolFilters.tool_name" placeholder="tool_name" clearable />
            <el-select v-model="toolFilters.status" placeholder="status" clearable>
              <el-option label="success" value="success" />
              <el-option label="blocked" value="blocked" />
              <el-option label="error" value="error" />
            </el-select>
            <el-select v-model="toolFilters.allowed" placeholder="allowed" clearable>
              <el-option label="allowed" value="true" />
              <el-option label="blocked" value="false" />
            </el-select>
            <el-input v-model="toolFilters.intent" placeholder="intent" clearable />
            <el-button type="primary" @click="loadToolCalls">筛选</el-button>
          </div>
          <el-table :data="toolCalls" v-loading="loading.tools" height="520" empty-text="暂无工具调用">
            <el-table-column prop="created_at" label="时间" min-width="170" show-overflow-tooltip />
            <el-table-column prop="tool_name" label="tool_name" min-width="190" show-overflow-tooltip />
            <el-table-column prop="tool_risk_level" label="risk" width="150" show-overflow-tooltip />
            <el-table-column label="allowed" width="100">
              <template #default="{ row }"><el-tag :type="row.allowed ? 'success' : 'warning'" size="small">{{ row.allowed ? 'yes' : 'no' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="status" label="status" width="100" />
            <el-table-column prop="blocked_reason" label="blocked_reason" min-width="160" show-overflow-tooltip />
            <el-table-column prop="latency_ms" label="latency" width="90" />
            <el-table-column prop="intent" label="intent" min-width="130" show-overflow-tooltip />
            <el-table-column prop="query_fact_type" label="fact_type" min-width="130" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="每日回放" name="evals">
          <div class="action-row">
            <el-button @click="runDryEval">Dry-run 回放</el-button>
            <el-button type="warning" @click="runApplyEval">Apply 回放</el-button>
            <el-button @click="loadEvalRuns">刷新</el-button>
          </div>
          <el-table :data="evalRuns" v-loading="loading.evals" height="320" empty-text="暂无回放记录" @row-click="openRunDetail">
            <el-table-column prop="run_uid" label="run_uid" min-width="230" show-overflow-tooltip />
            <el-table-column prop="run_type" label="run_type" width="110" />
            <el-table-column prop="status" label="status" width="110" />
            <el-table-column label="total/passed/failed/error" width="190">
              <template #default="{ row }">{{ row.total_cases }}/{{ row.passed_cases }}/{{ row.failed_cases }}/{{ row.error_cases }}</template>
            </el-table-column>
            <el-table-column prop="started_at" label="started_at" min-width="170" show-overflow-tooltip />
          </el-table>
          <div v-if="selectedRun" class="detail-grid">
            <div>
              <h4>traces</h4>
              <el-table :data="selectedRun.traces || []" height="220" empty-text="暂无 trace">
                <el-table-column prop="case_uid" label="case_uid" min-width="140" show-overflow-tooltip />
                <el-table-column prop="status" label="status" width="90" />
                <el-table-column prop="intent" label="intent" width="130" />
                <el-table-column prop="query_fact_type" label="fact_type" width="130" />
              </el-table>
            </div>
            <div>
              <h4>failures</h4>
              <el-table :data="selectedRun.failures || []" height="220" empty-text="暂无 failure">
                <el-table-column prop="case_uid" label="case_uid" min-width="120" show-overflow-tooltip />
                <el-table-column prop="failure_type" label="failure_type" min-width="150" show-overflow-tooltip />
                <el-table-column prop="suggested_fix_area" label="fix_area" min-width="150" show-overflow-tooltip />
              </el-table>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="修复任务" name="repairs">
          <div class="action-row"><el-button @click="loadRepairs">刷新</el-button></div>
          <el-table :data="repairTasks" v-loading="loading.repairs" height="280" empty-text="暂无修复任务">
            <el-table-column prop="title" label="title" min-width="250" show-overflow-tooltip />
            <el-table-column prop="failure_count" label="failure_count" width="120" />
            <el-table-column prop="suggested_owner" label="owner" width="110" />
            <el-table-column prop="priority" label="priority" width="90" />
            <el-table-column prop="status" label="status" width="100" />
            <el-table-column label="suggested_files" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">{{ formatJsonList(row.suggested_files) }}</template>
            </el-table-column>
          </el-table>
          <el-table :data="evalFailures" height="260" empty-text="暂无失败记录" class="failure-table">
            <el-table-column prop="failure_type" label="failure_type" min-width="160" show-overflow-tooltip />
            <el-table-column prop="severity" label="severity" width="100" />
            <el-table-column prop="suggested_fix_area" label="fix_area" min-width="150" show-overflow-tooltip />
            <el-table-column prop="case_uid" label="case_uid" min-width="150" show-overflow-tooltip />
            <el-table-column prop="failed_contract" label="failed_contract" min-width="160" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.ops-page { display: flex; flex-direction: column; gap: 14px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-card { background: #fff; border: 1px solid var(--kb-border-light); border-radius: 8px; padding: 14px 16px; }
.metric-label { font-size: 13px; color: #606266; margin-bottom: 8px; }
.metric-value { font-size: 26px; font-weight: 700; }
.metric-value.primary { color: #409eff; }
.metric-value.success { color: #67c23a; }
.metric-value.warning { color: #e6a23c; }
.metric-value.danger { color: #f56c6c; }
.ops-card { border-radius: 8px; }
.filter-row, .action-row { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.filter-row :deep(.el-input), .filter-row :deep(.el-select) { width: 180px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
.detail-grid h4 { margin: 0 0 8px; font-size: 14px; color: #303133; }
.failure-table { margin-top: 14px; }
@media (max-width: 1100px) {
  .summary-grid, .detail-grid { grid-template-columns: 1fr; }
}
</style>
