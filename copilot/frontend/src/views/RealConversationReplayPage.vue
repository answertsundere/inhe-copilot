<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchRealConversationRun,
  fetchRealConversationRuns,
  submitRealConversationReview,
  type RealConversationRun,
  type RealConversationTurnTrace,
} from '../api/realConversationEval'

const loading = ref(false)
const forbidden = ref(false)
const runs = ref<RealConversationRun[]>([])
const selectedRun = ref<RealConversationRun | null>(null)
const turns = ref<RealConversationTurnTrace[]>([])
const selectedTurn = ref<RealConversationTurnTrace | null>(null)
const reviewReason = ref('')

const groupedTurns = computed(() => {
  const groups = new Map<string, RealConversationTurnTrace[]>()
  for (const turn of turns.value) {
    const key = turn.case_uid || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(turn)
  }
  return Array.from(groups.entries()).map(([caseUid, items]) => ({ caseUid, items }))
})

function formatJson(value: unknown) {
  return JSON.stringify(value || {}, null, 2)
}

async function loadRuns() {
  loading.value = true
  forbidden.value = false
  try {
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

async function loadRun(run: RealConversationRun) {
  selectedRun.value = run
  selectedTurn.value = null
  loading.value = true
  try {
    const data = await fetchRealConversationRun(run.run_uid)
    turns.value = data.turns || []
    selectedTurn.value = turns.value[0] || null
  } catch (error: any) {
    if (error?.response?.status === 403) forbidden.value = true
    else ElMessage.error(error?.response?.data?.error || '加载回放详情失败')
  } finally {
    loading.value = false
  }
}

async function review(decision: 'correct' | 'incorrect' | 'needs_review') {
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
          <span class="run-meta">{{ run.status }} · {{ run.total_turns }} 轮</span>
          <span class="run-score">
            通过 {{ run.passed_turns }} / 失败 {{ run.failed_turns }} / 复核 {{ run.requires_review_turns }}
          </span>
        </button>
      </aside>

      <main class="chat-panel">
        <div class="panel-title">真实长对话回放</div>
        <el-empty v-if="!turns.length" description="选择左侧批次查看逐轮回放" />
        <section v-for="group in groupedTurns" :key="group.caseUid" class="conversation-group">
          <div class="case-title">{{ group.caseUid }}</div>
          <article
            v-for="turn in group.items"
            :key="turn.turn_uid"
            class="turn-card"
            :class="{ selected: selectedTurn?.turn_uid === turn.turn_uid, failed: !turn.passed }"
            @click="selectedTurn = turn"
          >
            <div class="bubble buyer">
              <span class="bubble-label">买家</span>
              <p>{{ turn.buyer_message }}</p>
            </div>
            <div class="bubble agent">
              <span class="bubble-label">Agent</span>
              <p>{{ turn.agent_reply || '未生成回复' }}</p>
              <div class="badges">
                <el-tag size="small" :type="turn.passed ? 'success' : 'danger'">
                  {{ turn.passed ? '通过' : '失败' }}
                </el-tag>
                <el-tag v-if="turn.requires_human_review" size="small" type="warning">需人工复核</el-tag>
                <el-tag v-if="turn.query_fact_type" size="small">{{ turn.query_fact_type }}</el-tag>
              </div>
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
              <span>fact type</span>
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

          <el-tabs>
            <el-tab-pane label="选中证据">
              <pre>{{ formatJson(selectedTurn.selected_evidence) }}</pre>
            </el-tab-pane>
            <el-tab-pane label="拒绝证据">
              <pre>{{ formatJson(selectedTurn.rejected_evidence) }}</pre>
            </el-tab-pane>
            <el-tab-pane label="answer_trace">
              <pre>{{ formatJson(selectedTurn.answer_trace) }}</pre>
            </el-tab-pane>
            <el-tab-pane label="final audit">
              <pre>{{ formatJson(selectedTurn.final_audit) }}</pre>
            </el-tab-pane>
          </el-tabs>

          <el-input
            v-model="reviewReason"
            type="textarea"
            :rows="3"
            placeholder="人工复核备注"
          />
          <div class="review-actions">
            <el-button type="success" @click="review('correct')">AI 正确</el-button>
            <el-button type="danger" @click="review('incorrect')">AI 错误</el-button>
            <el-button @click="review('needs_review')">继续复核</el-button>
          </div>
        </template>
      </aside>
    </template>
  </div>
</template>

<style scoped>
.real-replay-page {
  display: grid;
  grid-template-columns: 280px minmax(420px, 1fr) 420px;
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

.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--kb-text-primary);
  margin-bottom: 12px;
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
.run-score {
  display: block;
}

.run-id {
  font-weight: 700;
  color: var(--kb-text-primary);
  font-size: 13px;
}

.run-meta,
.run-score {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-top: 4px;
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

.bubble {
  max-width: 82%;
  margin-bottom: 10px;
}

.bubble p {
  margin: 4px 0 0;
  line-height: 1.6;
  white-space: pre-wrap;
}

.bubble-label {
  font-size: 12px;
  color: var(--kb-text-secondary);
}

.agent {
  margin-left: auto;
  background: #f8fafc;
  border-radius: 8px;
  padding: 8px;
}

.buyer {
  background: #f0fdf4;
  border-radius: 8px;
  padding: 8px;
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.metric-grid div {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 8px;
  background: #fff;
}

.metric-grid span,
.metric-grid strong {
  display: block;
}

.metric-grid span {
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.metric-grid strong {
  color: var(--kb-text-primary);
  margin-top: 4px;
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
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
</style>
