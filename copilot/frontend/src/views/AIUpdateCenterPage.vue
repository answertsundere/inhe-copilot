<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteBadCase, getAICenterOverview, getBadCaseDetail, rebuildRagIndex } from '../api/aiUpdate'

const loading = ref(false)
const rebuilding = ref(false)
const detailLoading = ref(false)
const detailVisible = ref(false)
const currentCase = ref<Record<string, any> | null>(null)

const data = ref<any>({
  summary: {},
  failure_types: {},
  learning_summary: {},
  failed_cases: [],
  rag_summary: {},
  rag_issues: [],
  recent_knowledge_updates: [],
})

const cards = computed(() => [
  { label: '未关闭失败', value: data.value.summary?.open_bad_case ?? 0, tone: 'danger' },
  { label: '未学习', value: getLearningCount('未学习'), tone: 'warning' },
  { label: '索引未同步', value: data.value.summary?.rag_not_ready ?? 0, tone: 'warning' },
  { label: '索引失败', value: data.value.summary?.rag_failed ?? 0, tone: 'danger' },
])

const failureTypeRows = computed(() => {
  return Object.entries(data.value.failure_types || {})
    .map(([name, count]) => ({ name, count }))
    .sort((a: any, b: any) => Number(b.count) - Number(a.count))
})

function getLearningCount(label: string) {
  const summary = data.value.learning_summary || {}
  return summary[label] ?? summary['鏈涔?'] ?? 0
}

function statusType(status: string) {
  if (['已复测通过', 'ready', 'verified'].includes(status)) return 'success'
  if (['已修复待复测', '处理中', 'fixed', 'fixing', 'triaged'].includes(status)) return 'warning'
  if (['failed', '未学习', 'open'].includes(status)) return 'danger'
  return 'info'
}

function shortText(value: any, max = 80) {
  const text = String(value || '')
  return text.length > max ? `${text.slice(0, max)}...` : text
}

function formatJson(value: any) {
  if (!value) return ''
  if (typeof value !== 'string') return JSON.stringify(value, null, 2)
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

async function fetchOverview() {
  loading.value = true
  try {
    const res = await getAICenterOverview()
    data.value = res.data
  } catch {
    ElMessage.error('AI 中心数据读取失败')
  } finally {
    loading.value = false
  }
}

async function openBadCaseDetail(row: any) {
  detailVisible.value = true
  detailLoading.value = true
  currentCase.value = row
  try {
    const res = await getBadCaseDetail(row.id)
    currentCase.value = res.data
  } catch {
    ElMessage.error('详情读取失败')
  } finally {
    detailLoading.value = false
  }
}

async function handleDeleteBadCase(row: any) {
  try {
    await ElMessageBox.confirm(
      `确认删除失败记录「${row.id}」吗？删除后不会再出现在失败清单和原因分布里。`,
      '删除失败记录',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteBadCase(row.id)
    ElMessage.success('已删除失败记录')
    if (currentCase.value?.id === row.id) {
      detailVisible.value = false
      currentCase.value = null
    }
    fetchOverview()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.error || '删除失败')
  }
}

async function handleRebuild() {
  try {
    await ElMessageBox.confirm(
      '会重新整理所有已发布知识给 AI 检索使用，期间可能稍慢。确认继续吗？',
      '重建检索索引',
      { type: 'warning' },
    )
  } catch {
    return
  }
  rebuilding.value = true
  try {
    const { data: result } = await rebuildRagIndex()
    ElMessage.success(`重建完成：成功 ${result.succeeded ?? 0}，失败 ${result.failed ?? 0}`)
    fetchOverview()
  } catch {
    ElMessage.error('重建失败')
  } finally {
    rebuilding.value = false
  }
}

onMounted(fetchOverview)
</script>

<template>
  <div class="ai-center" v-loading="loading">
    <section class="page-head">
      <div>
        <h2>AI 更新中心</h2>
        <p>看测试失败有没有闭环、知识更新后 AI 检索是否同步。</p>
      </div>
      <div class="head-actions">
        <el-button @click="fetchOverview">刷新</el-button>
        <el-button type="primary" :loading="rebuilding" @click="handleRebuild">重建检索索引</el-button>
      </div>
    </section>

    <section class="metric-grid">
      <div v-for="card in cards" :key="card.label" class="metric-card" :class="card.tone">
        <strong>{{ card.value }}</strong>
        <span>{{ card.label }}</span>
      </div>
    </section>

    <section class="main-grid">
      <div class="panel large">
        <div class="panel-head">
          <h3>测试失败清单</h3>
          <span>客服标记失败或沉淀 Bad Case 后，会在这里出现</span>
        </div>
        <el-table :data="data.failed_cases" stripe height="430">
          <el-table-column prop="id" label="编号" width="100" />
          <el-table-column prop="failure_type" label="失败原因" width="150" />
          <el-table-column label="学习状态" width="120">
            <template #default="{ row }">
              <el-tag :type="statusType(row.learning_status)" size="small">{{ row.learning_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="customer_message" label="客户问题" min-width="210" show-overflow-tooltip />
          <el-table-column prop="root_cause" label="根因/备注" min-width="170" show-overflow-tooltip />
          <el-table-column prop="fix_note" label="修复记录" min-width="150" show-overflow-tooltip />
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openBadCaseDetail(row)">详情</el-button>
              <el-button link type="danger" size="small" @click="handleDeleteBadCase(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h3>失败原因分布</h3>
          <span>看项目优先修哪里</span>
        </div>
        <div class="reason-list">
          <div v-for="row in failureTypeRows" :key="row.name" class="reason-row">
            <span>{{ row.name }}</span>
            <strong>{{ row.count }}</strong>
          </div>
          <el-empty v-if="failureTypeRows.length === 0" description="暂无失败记录" />
        </div>
      </div>
    </section>

    <section class="main-grid">
      <div class="panel large">
        <div class="panel-head">
          <h3>知识库和检索同步状态</h3>
          <span>重点看“已发布但索引没好”的条目</span>
        </div>
        <div class="rag-summary">
          <span>已发布：{{ data.rag_summary?.published_total ?? 0 }}</span>
          <span>可检索：{{ data.rag_summary?.ready ?? 0 }}</span>
          <span>未同步：{{ data.rag_summary?.not_ready ?? 0 }}</span>
          <span>无分片：{{ data.rag_summary?.zero_chunk ?? 0 }}</span>
        </div>
        <el-table :data="data.rag_issues" stripe height="320">
          <el-table-column prop="entry_id" label="ID" width="80" />
          <el-table-column prop="title" label="知识标题" min-width="260" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column prop="index_status" label="索引" width="110" />
          <el-table-column prop="chunk_count" label="分片" width="80" />
          <el-table-column prop="updated_at" label="更新时间" width="170" />
        </el-table>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h3>最近知识更新</h3>
          <span>看大家更新后是否已经变成可检索</span>
        </div>
        <div class="update-list">
          <div v-for="row in data.recent_knowledge_updates" :key="row.entry_id" class="update-row">
            <div>
              <strong>{{ row.title }}</strong>
              <span>ID {{ row.entry_id }} / {{ row.status }}</span>
            </div>
            <el-tag :type="statusType(row.index_status)" size="small">{{ row.index_status }}</el-tag>
          </div>
          <el-empty v-if="!data.recent_knowledge_updates?.length" description="暂无更新" />
        </div>
      </div>
    </section>

    <el-drawer v-model="detailVisible" title="失败记录详情" size="58%" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="currentCase">
          <div class="detail-actions">
            <el-button type="danger" @click="handleDeleteBadCase(currentCase)">删除这条记录</el-button>
          </div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="编号">{{ currentCase.id }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ currentCase.status || '-' }}</el-descriptions-item>
            <el-descriptions-item label="失败原因">{{ currentCase.failure_type || '-' }}</el-descriptions-item>
            <el-descriptions-item label="严重程度">{{ currentCase.severity || '-' }}</el-descriptions-item>
            <el-descriptions-item label="场景">{{ currentCase.scenario || '-' }}</el-descriptions-item>
            <el-descriptions-item label="来源">{{ currentCase.source || '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ currentCase.created_at || '-' }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ currentCase.updated_at || '-' }}</el-descriptions-item>
          </el-descriptions>

          <div class="detail-block">
            <h4>客户问题</h4>
            <p>{{ currentCase.customer_message || '-' }}</p>
          </div>
          <div class="detail-block">
            <h4>AI 建议回复</h4>
            <p>{{ currentCase.ai_suggested_reply || '-' }}</p>
          </div>
          <div class="detail-block">
            <h4>人工最终回复 / 客服修改稿</h4>
            <p>{{ currentCase.csr_final_reply || '-' }}</p>
          </div>
          <div class="detail-block">
            <h4>根因 / 备注</h4>
            <p>{{ currentCase.root_cause || currentCase.reject_reason || currentCase.auto_create_reason || '-' }}</p>
          </div>
          <div class="detail-block">
            <h4>修复记录</h4>
            <p>{{ currentCase.fix_note || '-' }}</p>
          </div>
          <div class="detail-grid">
            <div class="detail-block">
              <h4>实际工具</h4>
              <pre>{{ shortText(formatJson(currentCase.actual_tools_json), 2000) || '-' }}</pre>
            </div>
            <div class="detail-block">
              <h4>检索证据</h4>
              <pre>{{ shortText(formatJson(currentCase.retrieved_evidence_json || currentCase.used_evidence_json), 2000) || '-' }}</pre>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.ai-center { max-width: 1440px; }
.page-head,
.panel,
.metric-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
}
.page-head h2,
.panel-head h3 { margin: 0; color: #0f172a; }
.page-head p,
.panel-head span,
.update-row span { color: #64748b; font-size: 13px; }
.head-actions { display: flex; gap: 8px; }
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0;
}
.metric-card { padding: 16px; }
.metric-card strong { display: block; font-size: 30px; color: #0f172a; }
.metric-card.danger { border-color: #fecaca; background: #fff7f7; }
.metric-card.warning { border-color: #fde68a; background: #fffbeb; }
.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}
.panel { padding: 16px; min-width: 0; }
.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.reason-list,
.update-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 430px;
  overflow: auto;
}
.reason-row,
.update-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}
.update-row div { display: flex; flex-direction: column; min-width: 0; }
.update-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rag-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.rag-summary span {
  padding: 5px 10px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
}
.detail-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
.detail-block {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}
.detail-block h4 { margin: 0 0 8px; color: #0f172a; }
.detail-block p { margin: 0; color: #334155; line-height: 1.7; white-space: pre-wrap; }
.detail-block pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
@media (max-width: 980px) {
  .metric-grid,
  .main-grid,
  .detail-grid { grid-template-columns: 1fr; }
  .page-head {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
