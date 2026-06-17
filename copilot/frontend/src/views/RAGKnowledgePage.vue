<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getRAGEntries, getRAGEntry, submitRAGEntryReview, reviewRAGEntry,
  publishRAGEntry, archiveRAGEntry, rollbackRAGEntry,
  getRAGEntryVersions, getRAGEntryAuditLog,
  batchSubmitReview, getRAGSummary,
} from '../api/rag'
import StatusTag from '../components/common/StatusTag.vue'
import RiskBadge from '../components/common/RiskBadge.vue'

// ─── State ───
const loading = ref(false)
const entries = ref<any[]>([])
const total = ref(0)
const selectedIds = ref<number[]>([])
const summary = ref<Record<string, number>>({})

const filters = reactive({
  search: '',
  source_type: '',
  fact_type: '',
  intent: '',
  product_id: '',
  sku_id: '',
  business_key: '',
  batch_id: '',
  status: '',
  index_status: '',
  risk_level: '',
  human_review_required: '',
  auto_reply_allowed: '',
  sort_by: 'updated_at',
  sort_order: 'desc',
  page: 1,
  page_size: 20,
})

// Detail drawer
const drawerVisible = ref(false)
const currentEntry = ref<any>(null)
const detailLoading = ref(false)
const activeTab = ref('basic')
const versions = ref<any[]>([])
const auditLog = ref<any[]>([])

// ─── Labels ───
const statusLabels: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  published: '已发布',
  rejected: '已驳回',
  archived: '已归档',
}

const indexStatusLabels: Record<string, string> = {
  pending: '待索引',
  ready: '已就绪',
  failed: '索引失败',
  removed: '已移除',
}

const indexStatusTypes: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
  pending: 'warning',
  ready: 'success',
  failed: 'danger',
  removed: 'info',
}

// ─── Data Loading ───
async function fetchEntries() {
  loading.value = true
  try {
    const params: Record<string, any> = {
      limit: filters.page_size,
      offset: (filters.page - 1) * filters.page_size,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    }
    if (filters.search) params.q = filters.search
    if (filters.source_type) params.source_type = filters.source_type
    if (filters.fact_type) params.fact_type = filters.fact_type
    if (filters.intent) params.intent = filters.intent
    if (filters.product_id) params.product_id = filters.product_id
    if (filters.sku_id) params.sku_id = filters.sku_id
    if (filters.business_key) params.business_key = filters.business_key
    if (filters.batch_id) params.batch_id = filters.batch_id
    if (filters.status) params.status = filters.status
    if (filters.index_status) params.index_status = filters.index_status
    if (filters.risk_level) params.risk_level = filters.risk_level
    if (filters.human_review_required) params.human_review_required = filters.human_review_required
    if (filters.auto_reply_allowed) params.auto_reply_allowed = filters.auto_reply_allowed

    const { data } = await getRAGEntries(params)
    entries.value = data.items || []
    total.value = data.total || 0
  } catch {
    ElMessage.error('加载 RAG 知识条目失败')
  } finally {
    loading.value = false
  }
}

async function fetchSummary() {
  try {
    const { data } = await getRAGSummary()
    summary.value = data
  } catch { /* non-critical */ }
}

// ─── Detail ───
async function openDetail(id: number) {
  detailLoading.value = true
  drawerVisible.value = true
  activeTab.value = 'basic'
  currentEntry.value = null
  versions.value = []
  auditLog.value = []
  try {
    const { data } = await getRAGEntry(id)
    currentEntry.value = data
    const [versionsRes, auditRes] = await Promise.allSettled([
      getRAGEntryVersions(id), getRAGEntryAuditLog(id),
    ])
    versions.value = versionsRes.status === 'fulfilled' ? versionsRes.value.data.items || [] : []
    auditLog.value = auditRes.status === 'fulfilled' ? auditRes.value.data.items || [] : []
  } catch {
    ElMessage.error('加载详情失败')
  } finally {
    detailLoading.value = false
  }
}

// ─── Lifecycle Actions ───
async function handleSubmitReview(id: number) {
  try {
    await submitRAGEntryReview(id)
    ElMessage.success('已提交审核')
    openDetail(id)
    fetchEntries()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || '提交失败')
  }
}

async function handleApprove(id: number) {
  try {
    await ElMessageBox.confirm('确认审核通过此条目？', '审核确认')
  } catch { return }
  try {
    await reviewRAGEntry(id, { approved: true })
    ElMessage.success('审核通过')
    openDetail(id)
    fetchEntries()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || '审核失败')
  }
}

async function handleReject(id: number) {
  try {
    const { value } = await ElMessageBox.prompt('请输入驳回原因', '驳回', {
      inputPlaceholder: '驳回原因（可选）',
    })
    await reviewRAGEntry(id, { approved: false, reason: value || '' })
    ElMessage.success('已驳回')
    openDetail(id)
    fetchEntries()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.error || '驳回失败')
  }
}

async function handleArchive(id: number) {
  try {
    await ElMessageBox.confirm('确认归档此条目？归档后不再参与检索。', '归档确认')
  } catch { return }
  try {
    await archiveRAGEntry(id)
    ElMessage.success('已归档')
    drawerVisible.value = false
    fetchEntries()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || '归档失败')
  }
}

async function handleRollback(id: number) {
  try {
    const { value } = await ElMessageBox.prompt('请输入要回滚到的版本号', '回滚', {
      inputPlaceholder: '版本号',
    })
    const ver = parseInt(value, 10)
    if (isNaN(ver)) { ElMessage.warning('请输入有效的版本号'); return }
    await rollbackRAGEntry(id, ver)
    ElMessage.success('已回滚')
    openDetail(id)
    fetchEntries()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.error || '回滚失败')
  }
}

// ─── Batch ───
async function handleBatchSubmitReview() {
  if (!selectedIds.value.length) { ElMessage.warning('请先勾选条目'); return }
  try {
    await ElMessageBox.confirm(`确定对 ${selectedIds.value.length} 个条目提交审核？`, '批量提交确认')
  } catch { return }
  try {
    const { data } = await batchSubmitReview(selectedIds.value)
    const success = data.success || 0
    const failed = (data.results || []).filter((r: any) => r.status === 'error')
    ElMessage.success(`批量提交完成：成功 ${success}，失败 ${failed.length}`)
    if (failed.length) {
      for (const f of failed) {
        ElMessage.warning(`ID ${f.entry_id}: ${f.reason}`)
      }
    }
    selectedIds.value = []
    fetchEntries()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.error || '批量提交失败')
  }
}

function handleSelectionChange(rows: any[]) {
  selectedIds.value = rows.map((r: any) => r.id)
}

function resetFilters() {
  Object.assign(filters, {
    search: '', source_type: '', fact_type: '', intent: '',
    product_id: '', sku_id: '', business_key: '', batch_id: '',
    status: '', index_status: '', risk_level: '',
    human_review_required: '', auto_reply_allowed: '',
    sort_by: 'updated_at', sort_order: 'desc', page: 1,
  })
  fetchEntries()
}

// ─── URL Sync ───
watch(() => filters, () => {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, String(v)) })
  history.replaceState(null, '', `${location.pathname}?${params}`)
}, { deep: true })

onMounted(() => {
  const params = new URLSearchParams(location.search)
  params.forEach((v, k) => { if (k in filters) (filters as any)[k] = isNaN(Number(v)) ? v : Number(v) })
  fetchEntries()
  fetchSummary()
})
</script>

<template>
  <div class="rag-page">
    <!-- Info Banner -->
    <el-alert
      title="此页面管理用于 RAG 检索的 knowledge_entries。只有 published 且 index_status=ready 的条目才会进入正式检索。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <!-- Summary Stats -->
    <div v-if="summary.total_entries" style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
      <el-tag size="small">总计 {{ summary.total_entries }}</el-tag>
      <el-tag size="small" type="info">草稿 {{ summary.draft }}</el-tag>
      <el-tag size="small" type="warning">待审核 {{ summary.pending_review }}</el-tag>
      <el-tag size="small" type="success">已发布 {{ summary.published }}</el-tag>
      <el-tag size="small" type="success" v-if="summary.published_ready_count">可检索 {{ summary.published_ready_count }}</el-tag>
      <el-tag size="small">分片 {{ summary.chunk_count }}</el-tag>
    </div>

    <!-- Filter Bar -->
    <div class="filter-bar">
      <el-input v-model="filters.search" placeholder="搜索标题/内容" clearable size="small" style="width:180px" @clear="fetchEntries" @keyup.enter="fetchEntries" />
      <el-select v-model="filters.source_type" placeholder="source_type" clearable size="small" @change="fetchEntries" style="width:130px">
        <el-option label="product_identity" value="product_identity" />
        <el-option label="product_facts" value="product_facts" />
        <el-option label="faq" value="faq" />
        <el-option label="shipping_policy" value="shipping_policy" />
        <el-option label="high_risk_sop" value="high_risk_sop" />
      </el-select>
      <el-input v-model="filters.fact_type" placeholder="fact_type" clearable size="small" style="width:100px" @clear="fetchEntries" @keyup.enter="fetchEntries" />
      <el-input v-model="filters.product_id" placeholder="product_id" clearable size="small" style="width:100px" @clear="fetchEntries" @keyup.enter="fetchEntries" />
      <el-input v-model="filters.sku_id" placeholder="sku_id" clearable size="small" style="width:100px" @clear="fetchEntries" @keyup.enter="fetchEntries" />
      <el-input v-model="filters.business_key" placeholder="business_key" clearable size="small" style="width:160px" @clear="fetchEntries" @keyup.enter="fetchEntries" />
      <el-input v-model="filters.batch_id" placeholder="batch_id" clearable size="small" style="width:180px" @clear="fetchEntries" @keyup.enter="fetchEntries" />
      <el-select v-model="filters.status" placeholder="状态" clearable size="small" @change="fetchEntries" style="width:100px">
        <el-option v-for="(label, key) in statusLabels" :key="key" :label="label" :value="key" />
      </el-select>
      <el-select v-model="filters.index_status" placeholder="索引状态" clearable size="small" @change="fetchEntries" style="width:100px">
        <el-option v-for="(label, key) in indexStatusLabels" :key="key" :label="label" :value="key" />
      </el-select>
      <el-select v-model="filters.risk_level" placeholder="风险等级" clearable size="small" @change="fetchEntries" style="width:100px">
        <el-option label="low" value="low" />
        <el-option label="medium" value="medium" />
        <el-option label="high" value="high" />
        <el-option label="critical" value="critical" />
      </el-select>
      <el-select v-model="filters.human_review_required" placeholder="需人工审核" clearable size="small" @change="fetchEntries" style="width:110px">
        <el-option label="是" value="true" />
        <el-option label="否" value="false" />
      </el-select>
      <el-select v-model="filters.auto_reply_allowed" placeholder="允许自动回复" clearable size="small" @change="fetchEntries" style="width:120px">
        <el-option label="是" value="true" />
        <el-option label="否" value="false" />
      </el-select>
      <el-button size="small" @click="resetFilters">重置筛选</el-button>
      <div style="flex:1"></div>
      <el-dropdown trigger="click" :disabled="!selectedIds.length">
        <el-button size="small" type="primary" :disabled="!selectedIds.length">批量操作 ({{ selectedIds.length }})</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="handleBatchSubmitReview">批量提交审核</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <!-- Table -->
    <el-table v-loading="loading" :data="entries" stripe size="small" @selection-change="handleSelectionChange" style="width:100%">
      <el-table-column type="selection" width="36" />
      <el-table-column label="ID" prop="id" width="60" sortable />
      <el-table-column label="标题" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <a class="entry-link" @click="openDetail(row.id)">{{ row.title || '(无标题)' }}</a>
        </template>
      </el-table-column>
      <el-table-column label="source_type" prop="source_type" width="120" show-overflow-tooltip />
      <el-table-column label="fact_type" prop="fact_type" width="100" show-overflow-tooltip>
        <template #default="{ row }">{{ row.fact_type || '-' }}</template>
      </el-table-column>
      <el-table-column label="intent" prop="intent" width="110" show-overflow-tooltip />
      <el-table-column label="product_id" prop="product_id" width="100" show-overflow-tooltip>
        <template #default="{ row }">{{ row.product_id || '-' }}</template>
      </el-table-column>
      <el-table-column label="business_key" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <span style="font-size:11px;color:#909399">{{ row.business_key || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="batch_id" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <span style="font-size:11px;color:#909399">{{ row.import_batch_id || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }"><StatusTag :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="索引状态" width="90">
        <template #default="{ row }">
          <el-tag :type="indexStatusTypes[row.index_status] || 'info'" size="small">
            {{ indexStatusLabels[row.index_status] || row.index_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="风险" width="70">
        <template #default="{ row }"><RiskBadge :level="row.risk_level" /></template>
      </el-table-column>
      <el-table-column label="confidence" width="85" align="center">
        <template #default="{ row }">{{ row.source_confidence != null ? row.source_confidence.toFixed(1) : '-' }}</template>
      </el-table-column>
      <el-table-column label="自动回复" width="70" align="center">
        <template #default="{ row }">
          <el-icon v-if="row.auto_reply_allowed" color="#67c23a"><CircleCheck /></el-icon>
          <el-icon v-else color="#909399"><CircleClose /></el-icon>
        </template>
      </el-table-column>
      <el-table-column label="需审核" width="60" align="center">
        <template #default="{ row }">
          <el-icon v-if="row.human_review_required" color="#e6a23c"><Warning /></el-icon>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ (row.updated_at || '').replace('T', ' ').slice(0, 19) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openDetail(row.id)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Pagination -->
    <div class="pagination-bar">
      <span class="total-text">共 {{ total }} 条</span>
      <el-pagination v-model:current-page="filters.page" :page-size="filters.page_size" :total="total" layout="prev, pager, next" @current-change="fetchEntries" />
    </div>

    <!-- Detail Drawer -->
    <el-drawer v-model="drawerVisible" :title="currentEntry?.title || '条目详情'" size="70%" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="currentEntry">
          <el-tabs v-model="activeTab">
            <!-- Tab 1: Basic Info -->
            <el-tab-pane label="基础信息" name="basic">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="ID">{{ currentEntry.id }}</el-descriptions-item>
                <el-descriptions-item label="状态"><StatusTag :status="currentEntry.status" /></el-descriptions-item>
                <el-descriptions-item label="索引状态">
                  <el-tag :type="indexStatusTypes[currentEntry.index_status] || 'info'" size="small">
                    {{ indexStatusLabels[currentEntry.index_status] || currentEntry.index_status }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="版本">{{ currentEntry.version }}</el-descriptions-item>
                <el-descriptions-item label="source_type">{{ currentEntry.source_type }}</el-descriptions-item>
                <el-descriptions-item label="intent">{{ currentEntry.intent }}</el-descriptions-item>
                <el-descriptions-item label="fact_type">{{ currentEntry.fact_type || '-' }}</el-descriptions-item>
                <el-descriptions-item label="fact_scope">{{ currentEntry.fact_scope || '-' }}</el-descriptions-item>
                <el-descriptions-item label="product_id">{{ currentEntry.product_id || '-' }}</el-descriptions-item>
                <el-descriptions-item label="sku_id">{{ currentEntry.sku_id || '-' }}</el-descriptions-item>
                <el-descriptions-item label="business_key" :span="2">
                  <span style="font-size:12px;word-break:break-all">{{ currentEntry.business_key || '-' }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="batch_id" :span="2">
                  <span style="font-size:12px">{{ currentEntry.import_batch_id || '-' }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="parent_entry_id">{{ currentEntry.parent_entry_id || '-' }}</el-descriptions-item>
                <el-descriptions-item label="风险等级">{{ currentEntry.risk_level }}</el-descriptions-item>
                <el-descriptions-item label="confidence">{{ currentEntry.source_confidence }}</el-descriptions-item>
                <el-descriptions-item label="自动回复">{{ currentEntry.auto_reply_allowed ? '是' : '否' }}</el-descriptions-item>
                <el-descriptions-item label="需人工审核">{{ currentEntry.human_review_required ? '是' : '否' }}</el-descriptions-item>
                <el-descriptions-item label="创建人">{{ currentEntry.created_by }}</el-descriptions-item>
                <el-descriptions-item label="更新人">{{ currentEntry.updated_by }}</el-descriptions-item>
                <el-descriptions-item label="product_scope" :span="2">{{ (currentEntry.product_scope || []).join(', ') || '-' }}</el-descriptions-item>
                <el-descriptions-item label="sku_scope" :span="2">{{ (currentEntry.sku_scope || []).join(', ') || '-' }}</el-descriptions-item>
                <el-descriptions-item label="condition_text" :span="2">{{ currentEntry.condition_text || '-' }}</el-descriptions-item>
                <el-descriptions-item label="更新时间" :span="2">{{ (currentEntry.updated_at || '').replace('T', ' ').slice(0, 19) }}</el-descriptions-item>
              </el-descriptions>

              <!-- Content -->
              <div style="margin-top:16px">
                <h4 style="margin:0 0 8px">内容</h4>
                <div class="content-box">{{ currentEntry.content }}</div>
              </div>

              <!-- Action Buttons -->
              <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">
                <el-button v-if="currentEntry.status === 'draft' || currentEntry.status === 'rejected'" type="warning" size="small" @click="handleSubmitReview(currentEntry.id)">提交审核</el-button>
                <el-button v-if="currentEntry.status === 'draft' || currentEntry.status === 'rejected'" size="small" @click="handleArchive(currentEntry.id)">归档</el-button>
                <el-button v-if="currentEntry.status === 'pending_review'" type="success" size="small" @click="handleApprove(currentEntry.id)">审核通过</el-button>
                <el-button v-if="currentEntry.status === 'pending_review'" type="danger" size="small" @click="handleReject(currentEntry.id)">驳回</el-button>
                <el-button v-if="currentEntry.status === 'pending_review'" size="small" @click="handleArchive(currentEntry.id)">归档</el-button>
                <el-button v-if="currentEntry.status === 'published'" size="small" @click="handleRollback(currentEntry.id)">回滚</el-button>
                <el-button v-if="currentEntry.status === 'published'" size="small" @click="handleArchive(currentEntry.id)">归档</el-button>
              </div>
            </el-tab-pane>

            <!-- Tab 2: Versions -->
            <el-tab-pane label="版本历史" name="versions">
              <el-timeline v-if="versions.length">
                <el-timeline-item v-for="v in versions" :key="v.id" :timestamp="(v.created_at || '').replace('T', ' ').slice(0, 19)" placement="top">
                  <el-card shadow="never">
                    <div><strong>版本 {{ v.version }}</strong> by {{ v.changed_by }}</div>
                    <div v-if="v.change_reason" style="color:#909399;font-size:12px;margin-top:4px">{{ v.change_reason }}</div>
                  </el-card>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-else description="暂无版本记录" />
            </el-tab-pane>

            <!-- Tab 3: Audit Log -->
            <el-tab-pane label="审计日志" name="audit">
              <el-table v-if="auditLog.length" :data="auditLog" size="small" stripe>
                <el-table-column label="操作" prop="action" width="120" />
                <el-table-column label="旧状态" prop="old_status" width="100" />
                <el-table-column label="新状态" prop="new_status" width="100" />
                <el-table-column label="操作人" prop="performed_by" width="100" />
                <el-table-column label="详情" prop="details" min-width="200" show-overflow-tooltip />
                <el-table-column label="时间" width="160">
                  <template #default="{ row }">{{ (row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="暂无审计日志" />
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.rag-page { padding: 16px; }
.filter-bar {
  display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
  background: #fff; padding: 10px 12px; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06); flex-wrap: wrap;
}
.entry-link { color: #409eff; cursor: pointer; font-weight: 500; font-size: 13px; }
.entry-link:hover { text-decoration: underline; }
.pagination-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; }
.total-text { font-size: 13px; color: #909399; }
.content-box {
  background: #f5f7fa; border-radius: 6px; padding: 12px 16px;
  font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-all;
  max-height: 400px; overflow-y: auto;
}
</style>
