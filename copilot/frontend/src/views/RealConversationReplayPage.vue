<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchEvalTrends,
  fetchRealConversationRun,
  fetchRealConversationRuns,
  fetchRepairTask,
  fetchRepairTasks,
  generateRepairTasks,
  submitRealConversationReview,
  updateRepairTask,
  verifyRepairTask,
  type EvalTrends,
  type RealConversationFailure,
  type RealConversationRepairTask,
  type RealConversationRun,
  type RealConversationRunSummary,
  type RealConversationTurnTrace,
  type ReviewDecision,
} from '../api/realConversationEval'

type TurnFilter =
  | 'all'
  | 'failed'
  | 'human_review'
  | 'rag_miss'
  | 'evidence_misuse'
  | 'semantic_mismatch'
  | 'unsafe_claim'
  | 'tool_policy_blocked'

const loading = ref(false)
const forbidden = ref(false)
const runs = ref<RealConversationRun[]>([])
const selectedRun = ref<RealConversationRun | null>(null)
const runSummary = ref<RealConversationRunSummary | null>(null)
const turns = ref<RealConversationTurnTrace[]>([])
const failures = ref<RealConversationFailure[]>([])
const selectedTurn = ref<RealConversationTurnTrace | null>(null)
const reviewReason = ref('')
const activeFilter = ref<TurnFilter>('all')
const repairTasks = ref<RealConversationRepairTask[]>([])
const selectedTask = ref<RealConversationRepairTask | null>(null)
const selectedTaskTraces = ref<RealConversationTurnTrace[]>([])
const selectedTaskFailures = ref<RealConversationFailure[]>([])
const taskStatusFilter = ref('')
const taskFixAreaFilter = ref('')
const taskOwnerFilter = ref('')
const taskAssignedTo = ref('')
const taskResolutionNote = ref('')
const trendDays = ref(7)
const trends = ref<EvalTrends | null>(null)

const filterOptions: Array<{ label: string; value: TurnFilter }> = [
  { label: '全部', value: 'all' },
  { label: '失败', value: 'failed' },
  { label: '需要人工复核', value: 'human_review' },
  { label: 'RAG 未命中', value: 'rag_miss' },
  { label: '证据错用', value: 'evidence_misuse' },
  { label: '语义不匹配', value: 'semantic_mismatch' },
  { label: '不安全承诺', value: 'unsafe_claim' },
  { label: '工具策略拦截', value: 'tool_policy_blocked' },
]

const reviewActions: Array<{ label: string; decision: ReviewDecision; type?: 'success' | 'danger' | 'warning' | 'primary' }> = [
  { label: '通过', decision: 'correct', type: 'success' },
  { label: '不通过', decision: 'incorrect', type: 'danger' },
  { label: '需要补知识', decision: 'needs_knowledge', type: 'primary' },
  { label: '需要改规则', decision: 'needs_rule', type: 'warning' },
  { label: '需要补素材', decision: 'needs_media' },
  { label: '需要人工策略', decision: 'needs_human_policy' },
]

const taskStatusOptions = [
  { label: '全部状态', value: '' },
  { label: 'open', value: 'open' },
  { label: 'in_progress', value: 'in_progress' },
  { label: 'resolved', value: 'resolved' },
  { label: 'ignored', value: 'ignored' },
]

const taskPriorityOptions = [
  { label: 'low', value: 'low' },
  { label: 'medium', value: 'medium' },
  { label: 'high', value: 'high' },
]

const trendDayOptions = [
  { label: '7 天', value: 7 },
  { label: '14 天', value: 14 },
  { label: '30 天', value: 30 },
]

const failuresByTurn = computed(() => {
  const map = new Map<string, RealConversationFailure[]>()
  for (const failure of failures.value) {
    if (!map.has(failure.turn_uid)) map.set(failure.turn_uid, [])
    map.get(failure.turn_uid)!.push(failure)
  }
  return map
})

const filteredTurns = computed(() => {
  if (activeFilter.value === 'all') return turns.value
  return turns.value.filter((turn) => {
    const turnFailures = failuresByTurn.value.get(turn.turn_uid) || []
    if (activeFilter.value === 'failed') return !turn.passed || turnFailures.length > 0
    if (activeFilter.value === 'human_review') return turn.requires_human_review
    return turnFailures.some((failure) => failure.failure_type === activeFilter.value)
  })
})

const groupedTurns = computed(() => {
  const groups = new Map<string, RealConversationTurnTrace[]>()
  for (const turn of filteredTurns.value) {
    const key = turn.case_uid || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(turn)
  }
  return Array.from(groups.entries()).map(([caseUid, items]) => ({ caseUid, items }))
})

const selectedFailures = computed(() => {
  if (!selectedTurn.value) return []
  return failuresByTurn.value.get(selectedTurn.value.turn_uid) || []
})

const taskFixAreaOptions = computed(() => {
  const values = Array.from(new Set(repairTasks.value.map((task) => task.suggested_fix_area).filter(Boolean))).sort()
  return [{ label: '全部修复区域', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const taskOwnerOptions = computed(() => {
  const values = Array.from(new Set(repairTasks.value.map((task) => task.suggested_owner).filter(Boolean))).sort()
  return [{ label: '全部负责人', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const trendTotals = computed(() => {
  const daily = trends.value?.daily || []
  const totalTurns = daily.reduce((sum, item) => sum + (item.total_turns || 0), 0)
  const failedTurns = daily.reduce((sum, item) => sum + (item.failed_turns || 0), 0)
  return {
    totalTurns,
    failedTurns,
    passRate: totalTurns ? (totalTurns - failedTurns) / totalTurns : 0,
  }
})

function formatJson(value: unknown) {
  return JSON.stringify(value || {}, null, 2)
}

function formatPercent(value?: number) {
  if (typeof value !== 'number') return '0%'
  return `${Math.round(value * 1000) / 10}%`
}

function runPassRate(run: RealConversationRun) {
  return run.total_turns ? formatPercent(run.passed_turns / run.total_turns) : '0%'
}

async function loadRuns() {
  loading.value = true
  forbidden.value = false
  try {
    await loadTrends()
    runs.value = await fetchRealConversationRuns()
    if (runs.value.length) {
      await loadRun(runs.value[0])
    }
  } catch (error: any) {
    if (error?.response?.status === 403) forbidden.value = true
    else ElMessage.error(error?.response?.data?.error || '加载真实回放批次失败')
  } finally {
    loading.value = false
  }
}

async function loadTrends() {
  trends.value = await fetchEvalTrends({
    days: trendDays.value,
    source: 'real_conversation',
  })
}

async function loadRun(run: RealConversationRun) {
  selectedRun.value = run
  selectedTurn.value = null
  activeFilter.value = 'all'
  loading.value = true
  try {
    const data = await fetchRealConversationRun(run.run_uid)
    turns.value = data.turns || []
    failures.value = data.failures || []
    runSummary.value = data.summary || null
    selectedTurn.value = turns.value[0] || null
    await loadRepairTasks()
  } catch (error: any) {
    if (error?.response?.status === 403) forbidden.value = true
    else ElMessage.error(error?.response?.data?.error || '加载回放详情失败')
  } finally {
    loading.value = false
  }
}

async function review(decision: ReviewDecision) {
  if (!selectedTurn.value) return
  await submitRealConversationReview({
    run_uid: selectedTurn.value.run_uid,
    case_uid: selectedTurn.value.case_uid,
    turn_uid: selectedTurn.value.turn_uid,
    decision,
    reason: reviewReason.value,
  })
  reviewReason.value = ''
  ElMessage.success('复核结果已保存')
}

async function loadRepairTasks() {
  const items = await fetchRepairTasks({
    run_uid: selectedRun.value?.run_uid,
    status: taskStatusFilter.value || undefined,
    suggested_fix_area: taskFixAreaFilter.value || undefined,
    suggested_owner: taskOwnerFilter.value || undefined,
  })
  repairTasks.value = items
  if (selectedTask.value && !items.some((task) => task.task_uid === selectedTask.value?.task_uid)) {
    selectedTask.value = null
    selectedTaskTraces.value = []
    selectedTaskFailures.value = []
  }
}

async function generateTasksForCurrentRun() {
  if (!selectedRun.value) return
  await ElMessageBox.confirm('只会生成质检修复任务，不会自动修改知识库或 Agent 规则。确认继续？', '生成修复任务', {
    confirmButtonText: '生成',
    cancelButtonText: '取消',
    type: 'warning',
  })
  const result = await generateRepairTasks(selectedRun.value.run_uid)
  await loadRepairTasks()
  ElMessage.success(`已生成 ${result.generated} 个任务，更新 ${result.updated} 个任务`)
}

async function openRepairTask(task: RealConversationRepairTask) {
  const detail = await fetchRepairTask(task.task_uid)
  selectedTask.value = detail.task
  selectedTaskTraces.value = detail.traces || []
  selectedTaskFailures.value = detail.failures || []
  taskAssignedTo.value = detail.task.assigned_to || ''
  taskResolutionNote.value = detail.task.resolution_note || ''
}

async function saveRepairTask(status?: RealConversationRepairTask['status'], priority?: RealConversationRepairTask['priority']) {
  if (!selectedTask.value) return
  const result = await updateRepairTask(selectedTask.value.task_uid, {
    status,
    priority,
    assigned_to: taskAssignedTo.value,
    resolution_note: taskResolutionNote.value,
  })
  selectedTask.value = result.task
  await loadRepairTasks()
  ElMessage.success('修复任务已更新')
}

async function previewRepairVerification() {
  if (!selectedTask.value) return
  const result = await verifyRepairTask(selectedTask.value.task_uid, { dry_run: true })
  ElMessage.info(`将验证 ${result.checked_turn_uids?.length || 0} 个关联轮次`)
}

async function runRepairVerification() {
  if (!selectedTask.value) return
  await ElMessageBox.confirm('会重新回放该任务关联样本，不会自动修改知识库或 Agent 规则。确认继续？', '回归验证', {
    confirmButtonText: '验证',
    cancelButtonText: '取消',
    type: 'warning',
  })
  const result = await verifyRepairTask(selectedTask.value.task_uid, { apply: true })
  if (result.task) {
    selectedTask.value = result.task
  }
  await loadRepairTasks()
  if (selectedTask.value) {
    await openRepairTask(selectedTask.value)
  }
  const status = result.task?.verification_status || 'unknown'
  ElMessage.success(`回归验证完成：${status}`)
}

onMounted(loadRuns)
</script>

<template>
  <div class="real-replay-page" v-loading="loading">
    <el-alert
      v-if="forbidden"
      title="当前角色无权访问运营监控"
      type="warning"
      show-icon
      :closable="false"
      class="permission-alert"
    />

    <template v-else>
      <aside class="run-list">
        <div class="panel-title">每日回放批次</div>
        <el-empty v-if="!runs.length" description="暂无回放批次" />
        <button
          v-for="run in runs"
          :key="run.run_uid"
          class="run-item"
          :class="{ active: selectedRun?.run_uid === run.run_uid }"
          @click="loadRun(run)"
        >
          <span class="run-id">{{ run.run_uid }}</span>
          <span class="run-meta">{{ run.status }} / 样本 {{ run.total_cases }} / 轮次 {{ run.total_turns }}</span>
          <span class="run-score">通过 {{ run.passed_turns }} / 失败 {{ run.failed_turns }} / 复核 {{ run.requires_review_turns }}</span>
          <span class="run-rate">通过率 {{ runPassRate(run) }}</span>
        </button>
      </aside>

      <main class="chat-panel">
        <div class="panel-title">真实长对话回放</div>

        <section class="trend-panel">
          <div class="trend-header">
            <div class="sub-title">趋势报表</div>
            <el-segmented v-model="trendDays" :options="trendDayOptions" size="small" @change="loadTrends" />
          </div>
          <div class="trend-cards">
            <div>
              <span>区间通过率</span>
              <strong>{{ formatPercent(trendTotals.passRate) }}</strong>
            </div>
            <div>
              <span>回放轮次</span>
              <strong>{{ trendTotals.totalTurns }}</strong>
            </div>
            <div>
              <span>失败轮次</span>
              <strong>{{ trendTotals.failedTurns }}</strong>
            </div>
            <div>
              <span>最近回放</span>
              <strong>{{ trends?.latest_daily_replay?.status || '-' }}</strong>
            </div>
          </div>
          <div class="trend-grid">
            <div class="trend-box">
              <div class="mini-title">每日通过率</div>
              <div v-for="item in trends?.daily || []" :key="item.date" class="daily-row">
                <span>{{ item.date }}</span>
                <el-progress :percentage="Math.round((item.pass_rate || 0) * 100)" :stroke-width="8" />
                <em>{{ item.total_turns }} 轮 / 失败 {{ item.failed_turns }}</em>
              </div>
            </div>
            <div class="trend-box">
              <div class="mini-title">Top 失败类型</div>
              <div v-for="item in trends?.top_failure_types || []" :key="item.name" class="rank-row">
                <span>{{ item.name }}</span>
                <strong>{{ item.count }}</strong>
              </div>
              <div class="mini-title">Top 修复区域</div>
              <div v-for="item in trends?.top_fix_areas || []" :key="item.name" class="rank-row">
                <span>{{ item.name }}</span>
                <strong>{{ item.count }}</strong>
              </div>
            </div>
            <div class="trend-box">
              <div class="mini-title">修复任务状态</div>
              <div v-for="(count, status) in trends?.repair_task_status_counts || {}" :key="status" class="rank-row">
                <span>{{ status }}</span>
                <strong>{{ count }}</strong>
              </div>
              <div class="mini-title">修复区域分布</div>
              <div v-for="(count, area) in trends?.suggested_fix_area_counts || {}" :key="area" class="rank-row">
                <span>{{ area }}</span>
                <strong>{{ count }}</strong>
              </div>
            </div>
          </div>
        </section>

        <section v-if="selectedRun" class="summary-strip">
          <div>
            <span>通过率</span>
            <strong>{{ formatPercent(runSummary?.pass_rate) }}</strong>
          </div>
          <div>
            <span>平均耗时</span>
            <strong>{{ runSummary?.avg_latency_ms || 0 }} ms</strong>
          </div>
          <div>
            <span>人工复核</span>
            <strong>{{ runSummary?.requires_review_count || 0 }}</strong>
          </div>
          <div>
            <span>失败类型</span>
            <strong>{{ Object.keys(runSummary?.failure_counts_by_type || {}).length }}</strong>
          </div>
        </section>

        <el-segmented v-model="activeFilter" :options="filterOptions" class="filter-bar" />

        <el-empty v-if="!turns.length" description="选择左侧批次查看逐轮回放" />
        <el-empty v-else-if="!filteredTurns.length" description="当前筛选条件下没有样本" />
        <section v-for="group in groupedTurns" v-else :key="group.caseUid" class="conversation-group">
          <div class="case-title">{{ group.caseUid }}</div>
          <article
            v-for="turn in group.items"
            :key="turn.turn_uid"
            class="turn-card"
            :class="{ selected: selectedTurn?.turn_uid === turn.turn_uid, failed: !turn.passed }"
            @click="selectedTurn = turn"
          >
            <div class="turn-meta">
              <el-tag size="small" :type="turn.passed ? 'success' : 'danger'">
                {{ turn.passed ? '通过' : '失败' }}
              </el-tag>
              <el-tag v-if="turn.requires_human_review" size="small" type="warning">需人工复核</el-tag>
              <el-tag v-if="turn.query_fact_type" size="small">{{ turn.query_fact_type }}</el-tag>
              <span>{{ turn.latency_ms }} ms</span>
            </div>
            <div class="bubble buyer">
              <span class="bubble-label">买家原话</span>
              <p>{{ turn.buyer_message }}</p>
            </div>
            <div class="bubble reference">
              <span class="bubble-label">原客服回复参考</span>
              <p>{{ turn.reference_human_reply || '-' }}</p>
            </div>
            <div class="bubble agent">
              <span class="bubble-label">Agent 回复</span>
              <p>{{ turn.agent_reply || '未生成回复' }}</p>
            </div>
            <div v-if="failuresByTurn.get(turn.turn_uid)?.length" class="failure-tags">
              <el-tag
                v-for="failure in failuresByTurn.get(turn.turn_uid)"
                :key="`${turn.turn_uid}-${failure.failure_type}`"
                size="small"
                type="danger"
              >
                {{ failure.failure_type }} / {{ failure.suggested_fix_area || 'manual_triage' }}
              </el-tag>
            </div>
          </article>
        </section>
      </main>

      <aside class="trace-panel">
        <div class="panel-title">RAG 命中与审核</div>
        <el-empty v-if="!selectedTurn" description="点击一轮对话查看 trace" />
        <template v-else>
          <div class="metric-grid">
            <div>
              <span>query_fact_type</span>
              <strong>{{ selectedTurn.query_fact_type || '-' }}</strong>
            </div>
            <div>
              <span>耗时</span>
              <strong>{{ selectedTurn.latency_ms }} ms</strong>
            </div>
            <div>
              <span>选中证据</span>
              <strong>{{ selectedTurn.selected_evidence.length }}</strong>
            </div>
            <div>
              <span>拒绝证据</span>
              <strong>{{ selectedTurn.rejected_evidence.length }}</strong>
            </div>
          </div>

          <section v-if="selectedFailures.length" class="fix-panel">
            <div class="sub-title">失败归因与修复建议</div>
            <div v-for="failure in selectedFailures" :key="failure.failure_type" class="fix-item">
              <strong>{{ failure.failure_type }}</strong>
              <span>严重度：{{ failure.severity }}</span>
              <span>修复区域：{{ failure.suggested_fix_area || 'manual_triage' }}</span>
              <span>建议负责人：{{ failure.suggested_owner || '-' }}</span>
              <p>{{ failure.explanation || failure.message }}</p>
            </div>
          </section>

          <el-collapse class="trace-collapse">
            <el-collapse-item title="selected_evidence" name="selected_evidence">
              <pre>{{ formatJson(selectedTurn.selected_evidence) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="rejected_evidence" name="rejected_evidence">
              <pre>{{ formatJson(selectedTurn.rejected_evidence) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="answer_trace" name="answer_trace">
              <pre>{{ formatJson(selectedTurn.answer_trace) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="final_audit" name="final_audit">
              <pre>{{ formatJson(selectedTurn.final_audit) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="semantic_compiler" name="semantic_compiler">
              <pre>{{ formatJson(selectedTurn.semantic_compiler) }}</pre>
            </el-collapse-item>
          </el-collapse>

          <el-input
            v-model="reviewReason"
            type="textarea"
            :rows="3"
            placeholder="人工复核备注，不会自动写知识库"
          />
          <div class="review-actions">
            <el-button
              v-for="action in reviewActions"
              :key="action.decision"
              :type="action.type"
              @click="review(action.decision)"
            >
              {{ action.label }}
            </el-button>
          </div>
        </template>
        <section class="repair-task-panel">
          <div class="task-header">
            <div class="sub-title">修复任务队列</div>
            <el-button size="small" type="primary" :disabled="!selectedRun" @click="generateTasksForCurrentRun">
              从当前批次生成
            </el-button>
          </div>
          <div class="task-filters">
            <el-select v-model="taskStatusFilter" size="small" @change="loadRepairTasks">
              <el-option
                v-for="option in taskStatusOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="taskFixAreaFilter" size="small" @change="loadRepairTasks">
              <el-option
                v-for="option in taskFixAreaOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="taskOwnerFilter" size="small" @change="loadRepairTasks">
              <el-option
                v-for="option in taskOwnerOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </div>
          <el-empty v-if="!repairTasks.length" description="暂无修复任务" />
          <div v-else class="task-list">
            <button
              v-for="task in repairTasks"
              :key="task.task_uid"
              class="task-item"
              :class="{ active: selectedTask?.task_uid === task.task_uid }"
              @click="openRepairTask(task)"
            >
              <strong>{{ task.title || task.failure_type }}</strong>
              <span>{{ task.status }} / {{ task.priority }} / 样本 {{ task.sample_count }}</span>
              <span>验证 {{ task.verification_status }} / 通过率 {{ formatPercent(task.verification_summary?.pass_rate) }}</span>
              <span>{{ task.suggested_fix_area }} / {{ task.suggested_owner }}</span>
            </button>
          </div>
          <section v-if="selectedTask" class="task-detail">
            <div class="sub-title">任务详情</div>
            <p>{{ selectedTask.description }}</p>
            <div class="verification-panel">
              <div class="verification-line">
                <span>验证状态</span>
                <strong>{{ selectedTask.verification_status }}</strong>
              </div>
              <div class="verification-line">
                <span>上次验证</span>
                <strong>{{ selectedTask.last_verified_at || '-' }}</strong>
              </div>
              <div class="verification-line">
                <span>验证通过率</span>
                <strong>{{ formatPercent(selectedTask.verification_summary?.pass_rate) }}</strong>
              </div>
              <div v-if="selectedTask.verification_summary?.remaining_failure_types?.length" class="task-failure-tags">
                <el-tag
                  v-for="failureType in selectedTask.verification_summary.remaining_failure_types"
                  :key="failureType"
                  size="small"
                  type="danger"
                >
                  {{ failureType }}
                </el-tag>
              </div>
              <div class="task-controls">
                <el-button size="small" @click="previewRepairVerification">仅预览验证范围</el-button>
                <el-button size="small" type="warning" @click="runRepairVerification">回归验证</el-button>
              </div>
            </div>
            <div class="task-controls">
              <el-select v-model="selectedTask.status" size="small">
                <el-option
                  v-for="option in taskStatusOptions.filter((item) => item.value)"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-select v-model="selectedTask.priority" size="small">
                <el-option
                  v-for="option in taskPriorityOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </div>
            <el-input v-model="taskAssignedTo" size="small" placeholder="assigned_to" />
            <el-input
              v-model="taskResolutionNote"
              type="textarea"
              :rows="2"
              placeholder="处理备注，不会自动写知识库"
            />
            <el-button
              size="small"
              type="primary"
              @click="saveRepairTask(selectedTask.status, selectedTask.priority)"
            >
              保存任务状态
            </el-button>
            <div class="task-samples">
              <div v-if="selectedTaskFailures.length" class="task-failure-tags">
                <el-tag
                  v-for="failure in selectedTaskFailures"
                  :key="`${failure.turn_uid}-${failure.failure_type}`"
                  size="small"
                  type="danger"
                >
                  {{ failure.failure_type }}
                </el-tag>
              </div>
              <div v-for="trace in selectedTaskTraces" :key="trace.turn_uid" class="task-sample">
                <strong>{{ trace.turn_uid }}</strong>
                <span>{{ trace.query_fact_type || '-' }} / {{ trace.latency_ms }} ms</span>
                <p>{{ trace.buyer_message }}</p>
              </div>
            </div>
          </section>
        </section>
      </aside>
    </template>
  </div>
</template>

<style scoped>
.real-replay-page {
  display: grid;
  grid-template-columns: 280px minmax(460px, 1fr) 430px;
  gap: 16px;
  min-height: calc(100vh - 104px);
}

.permission-alert {
  grid-column: 1 / -1;
}

.run-list,
.chat-panel,
.trace-panel {
  min-height: 0;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px;
  overflow: auto;
}

.panel-title,
.sub-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--kb-text-primary);
  margin-bottom: 12px;
}

.sub-title {
  font-size: 13px;
  margin-bottom: 8px;
}

.run-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid var(--kb-border);
  background: #fff;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 10px;
  cursor: pointer;
}

.run-item.active {
  border-color: #3b82f6;
  background: #eff6ff;
}

.run-id,
.run-meta,
.run-score,
.run-rate {
  display: block;
}

.run-id {
  font-weight: 700;
  color: var(--kb-text-primary);
  font-size: 13px;
}

.run-meta,
.run-score,
.run-rate {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.trend-panel {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 10px;
  background: #fff;
  margin-bottom: 12px;
}

.trend-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.trend-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}

.trend-cards div,
.trend-box {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #f8fafc;
  padding: 8px;
}

.trend-cards span,
.daily-row span,
.daily-row em,
.rank-row span {
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.trend-cards strong {
  display: block;
  margin-top: 4px;
  color: var(--kb-text-primary);
}

.trend-grid {
  display: grid;
  grid-template-columns: minmax(240px, 1.2fr) 1fr 1fr;
  gap: 8px;
}

.mini-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--kb-text-primary);
  margin-bottom: 6px;
}

.daily-row {
  display: grid;
  grid-template-columns: 82px minmax(80px, 1fr) 86px;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.daily-row em {
  font-style: normal;
  text-align: right;
}

.rank-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
}

.summary-strip div,
.metric-grid div,
.fix-item {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 8px;
  background: #fff;
}

.summary-strip span,
.metric-grid span,
.fix-item span {
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.summary-strip strong,
.metric-grid strong {
  display: block;
  color: var(--kb-text-primary);
  margin-top: 4px;
}

.filter-bar {
  margin-bottom: 12px;
  max-width: 100%;
  overflow-x: auto;
}

.conversation-group {
  margin-bottom: 16px;
}

.case-title {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin: 12px 0 8px;
}

.turn-card {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fff;
  cursor: pointer;
}

.turn-card.selected {
  border-color: #3b82f6;
}

.turn-card.failed {
  border-color: #fca5a5;
}

.turn-meta,
.failure-tags,
.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.turn-meta {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-bottom: 10px;
}

.bubble {
  margin-bottom: 10px;
  border-radius: 8px;
  padding: 8px;
}

.bubble p,
.fix-item p {
  margin: 4px 0 0;
  line-height: 1.6;
  white-space: pre-wrap;
}

.bubble-label {
  font-size: 12px;
  color: var(--kb-text-secondary);
}

.buyer {
  background: #f0fdf4;
}

.reference {
  background: #fff7ed;
}

.agent {
  background: #f8fafc;
}

.failure-tags {
  margin-top: 8px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.fix-panel,
.trace-collapse {
  margin-bottom: 12px;
}

.repair-task-panel {
  border-top: 1px solid var(--kb-border);
  margin-top: 14px;
  padding-top: 14px;
}

.task-header,
.task-filters,
.task-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}

.task-header {
  justify-content: space-between;
}

.task-filters,
.task-controls {
  flex-wrap: wrap;
}

.task-filters .el-select,
.task-controls .el-select {
  width: 132px;
}

.task-list {
  display: grid;
  gap: 8px;
}

.task-item {
  width: 100%;
  text-align: left;
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #fff;
  padding: 8px;
  cursor: pointer;
}

.task-item.active {
  border-color: #3b82f6;
  background: #eff6ff;
}

.task-item strong,
.task-item span,
.task-sample strong,
.task-sample span {
  display: block;
}

.task-item span,
.task-sample span {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.task-detail {
  margin-top: 12px;
}

.verification-panel {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #f8fafc;
  padding: 8px;
  margin-bottom: 10px;
}

.verification-line {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  padding: 3px 0;
}

.verification-line span {
  color: var(--kb-text-secondary);
}

.verification-line strong {
  color: var(--kb-text-primary);
}

.task-detail .el-input {
  margin-bottom: 8px;
}

.task-samples {
  margin-top: 10px;
}

.task-failure-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.task-sample {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 8px;
  background: #f8fafc;
  margin-bottom: 8px;
}

.task-sample p {
  margin: 4px 0 0;
  line-height: 1.5;
  white-space: pre-wrap;
}

.fix-item {
  margin-bottom: 8px;
}

.fix-item strong,
.fix-item span {
  display: block;
}

pre {
  max-height: 300px;
  overflow: auto;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
}

.review-actions {
  margin-top: 10px;
}
</style>
