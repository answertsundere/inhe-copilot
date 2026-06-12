<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Check,
  Close,
  RefreshRight,
  Warning,
  Document,
  ChatDotRound,
  Goods,
  ArrowRight,
} from '@element-plus/icons-vue'
import { getReviews, getReview, approveReview, rejectReview, getReviewStats } from '../api/review'

interface ReviewItem {
  id: number
  target_type: string
  target_title: string
  change_summary: string
  priority: string
  risk_level: string
  requested_by: string
  created_at: string
  before_snapshot: Record<string, any>
  after_snapshot: Record<string, any>
  changed_fields: string[]
  status: string
}

interface ReviewStats {
  pending: number
  approved: number
  rejected: number
}

const loading = ref(false)
const reviewList = ref<ReviewItem[]>([])
const stats = ref<ReviewStats>({ pending: 0, approved: 0, rejected: 0 })
const selectedId = ref<number | null>(null)

// Detail
const detailLoading = ref(false)
const detail = ref<ReviewItem | null>(null)
const opinion = ref('')
const opinionDialogVisible = ref(false)

const priorityMap: Record<string, { label: string; type: string }> = {
  urgent: { label: '紧急', type: 'danger' },
  high: { label: '高', type: 'warning' },
  medium: { label: '中', type: '' },
  low: { label: '低', type: 'info' },
}

const riskColorMap: Record<string, string> = { low: '#67c23a', medium: '#e6a23c', high: '#f56c6c', critical: '#c45656' }
const riskLabelMap: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险', critical: '严重' }

const targetTypeIcon: Record<string, any> = {
  product: Goods,
  qa: ChatDotRound,
  sop: Document,
}

const sortedList = computed(() => {
  const order: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 }
  return [...reviewList.value].sort((a, b) => (order[a.priority] ?? 9) - (order[b.priority] ?? 9))
})

function formatValue(val: any): string {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'boolean') return val ? '是' : '否'
  if (Array.isArray(val)) return val.join(', ') || '-'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

async function fetchReviews() {
  loading.value = true
  try {
    const [listRes, statsRes] = await Promise.all([getReviews({ status: 'pending' }), getReviewStats()])
    reviewList.value = listRes.data?.items || []
    const sd = statsRes.data
    stats.value = { pending: sd.pending ?? 0, approved: sd.approved ?? 0, rejected: sd.rejected ?? 0 }
  } catch (e) {
    console.error('Failed to fetch reviews', e)
  } finally {
    loading.value = false
  }
}

async function selectReview(id: number) {
  selectedId.value = id
  detailLoading.value = true
  try {
    const { data } = await getReview(id)
    detail.value = data
  } catch {
    ElMessage.error('加载审核详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function handleApprove() {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm('确认通过该审核？', '审核确认', { type: 'success', confirmButtonText: '确认通过', cancelButtonText: '取消' })
    await approveReview(detail.value.id)
    ElMessage.success('已通过')
    removeCurrentAndRefresh()
  } catch { /* cancelled or error */ }
}

function showRejectDialog() {
  opinion.value = ''
  opinionDialogVisible.value = true
}

async function handleReject() {
  if (!detail.value) return
  if (!opinion.value.trim()) {
    ElMessage.warning('请填写驳回意见')
    return
  }
  try {
    await rejectReview(detail.value.id, opinion.value.trim())
    ElMessage.success('已驳回')
    opinionDialogVisible.value = false
    removeCurrentAndRefresh()
  } catch {
    ElMessage.error('操作失败')
  }
}

function handleSkip() {
  removeCurrentAndRefresh()
}

function removeCurrentAndRefresh() {
  reviewList.value = reviewList.value.filter((r) => r.id !== selectedId.value)
  detail.value = null
  selectedId.value = null
  fetchReviews()
}

function formatDate(d: string) {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(fetchReviews)
</script>

<template>
  <div class="review-page">
    <!-- Stats bar -->
    <div class="stats-bar">
      <div class="stat-item pending">
        <span class="stat-num">{{ stats.pending }}</span>
        <span class="stat-label">待审核</span>
      </div>
      <div class="stat-item approved">
        <span class="stat-num">{{ stats.approved }}</span>
        <span class="stat-label">已通过</span>
      </div>
      <div class="stat-item rejected">
        <span class="stat-num">{{ stats.rejected }}</span>
        <span class="stat-label">已驳回</span>
      </div>
    </div>

    <div class="page-body">
      <!-- Left: review list -->
      <div class="list-panel">
        <h4 class="panel-title">审核任务</h4>
        <el-skeleton :loading="loading" animated>
          <template #template>
            <div v-for="i in 5" :key="i" style="margin-bottom: 10px"><el-skeleton-item variant="rect" style="height: 90px; border-radius: 8px" /></div>
          </template>
          <template #default>
            <div
              v-for="item in sortedList"
              :key="item.id"
              class="review-task-card"
              :class="{ active: selectedId === item.id }"
              @click="selectReview(item.id)"
            >
              <div class="task-top">
                <el-icon class="task-type-icon" :size="16"><component :is="targetTypeIcon[item.target_type] || Document" /></el-icon>
                <span class="task-summary">{{ item.change_summary || item.target_title }}</span>
              </div>
              <div class="task-badges">
                <el-tag size="small" :type="(priorityMap[item.priority]?.type as any) || 'info'">
                  {{ priorityMap[item.priority]?.label || item.priority }}
                </el-tag>
                <el-tag size="small" :color="riskColorMap[item.risk_level]" effect="dark" style="border: none; color: #fff">
                  {{ riskLabelMap[item.risk_level] || item.risk_level }}
                </el-tag>
              </div>
              <div class="task-meta">
                <span>{{ item.requested_by }}</span>
                <span>{{ formatDate(item.created_at) }}</span>
              </div>
            </div>
            <el-empty v-if="!loading && sortedList.length === 0" description="暂无待审核任务" :image-size="60" />
          </template>
        </el-skeleton>
      </div>

      <!-- Right: detail -->
      <div class="detail-panel">
        <template v-if="!detail && !selectedId">
          <el-empty description="请从左侧选择一条审核任务" :image-size="100" />
        </template>
        <template v-else>
          <div v-loading="detailLoading">
            <template v-if="detail">
              <!-- Header -->
              <div class="detail-header">
                <div class="detail-title-row">
                  <el-tag :type="(priorityMap[detail.priority]?.type as any)">{{ priorityMap[detail.priority]?.label }}</el-tag>
                  <h3 class="detail-title">{{ detail.change_summary }}</h3>
                  <el-tag :color="riskColorMap[detail.risk_level]" effect="dark" style="border: none; color: #fff">
                    {{ riskLabelMap[detail.risk_level] || detail.risk_level }}
                  </el-tag>
                </div>
                <div class="detail-meta">
                  <span>类型: {{ detail.target_type }}</span>
                  <span>提交人: {{ detail.requested_by }}</span>
                  <span>{{ formatDate(detail.created_at) }}</span>
                </div>
              </div>

              <!-- Changed fields -->
              <div class="changed-fields">
                <span class="fields-label">变更字段：</span>
                <el-tag v-for="f in detail.changed_fields" :key="f" size="small" type="warning" style="margin-right: 6px">{{ f }}</el-tag>
              </div>

              <!-- Before/After comparison -->
              <el-row :gutter="16" class="comparison-row">
                <el-col :span="12">
                  <div class="comparison-panel before-panel">
                    <div class="panel-header"><el-icon color="#f56c6c"><Close /></el-icon> 修改前</div>
                    <div class="comparison-body">
                      <div v-for="f in detail.changed_fields" :key="'b-' + f" class="field-row">
                        <span class="field-name">{{ f }}</span>
                        <span class="field-value before-value">{{ formatValue(detail.before_snapshot?.[f]) }}</span>
                      </div>
                    </div>
                  </div>
                </el-col>
                <el-col :span="12">
                  <div class="comparison-panel after-panel">
                    <div class="panel-header"><el-icon color="#67c23a"><Check /></el-icon> 修改后</div>
                    <div class="comparison-body">
                      <div v-for="f in detail.changed_fields" :key="'a-' + f" class="field-row">
                        <span class="field-name">{{ f }}</span>
                        <span class="field-value after-value">{{ formatValue(detail.after_snapshot?.[f]) }}</span>
                      </div>
                    </div>
                  </div>
                </el-col>
              </el-row>

              <!-- Action buttons -->
              <div class="action-bar">
                <el-button type="success" :icon="Check" @click="handleApprove">通过</el-button>
                <el-button type="danger" :icon="Close" @click="showRejectDialog">驳回</el-button>
                <el-button :icon="RefreshRight" @click="handleSkip">跳过</el-button>
              </div>
            </template>
          </div>
        </template>
      </div>
    </div>

    <!-- Reject dialog -->
    <el-dialog v-model="opinionDialogVisible" title="驳回审核" width="480px" :close-on-click-modal="false">
      <el-input v-model="opinion" type="textarea" :rows="4" placeholder="请输入驳回意见..." />
      <template #footer>
        <el-button @click="opinionDialogVisible = false">取消</el-button>
        <el-button type="danger" @click="handleReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.review-page {
  height: 100%;
}

.stats-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.stat-item {
  background: #fff;
  border-radius: 8px;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.stat-item .stat-num {
  font-size: 24px;
  font-weight: 700;
}

.stat-item .stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-item.pending .stat-num { color: #e6a23c; }
.stat-item.approved .stat-num { color: #67c23a; }
.stat-item.rejected .stat-num { color: #f56c6c; }

.page-body {
  display: flex;
  gap: 16px;
  min-height: 0;
}

.list-panel {
  width: 340px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  overflow-y: auto;
  height: calc(100vh - 260px);
}

.panel-title {
  margin: 0 0 12px;
  font-size: 15px;
  color: #303133;
}

.review-task-card {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 8px;
  transition: all 0.2s;
}

.review-task-card:hover {
  border-color: #c0c4cc;
}

.review-task-card.active {
  border-color: #409eff;
  background: #ecf5ff;
}

.task-top {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 8px;
}

.task-type-icon {
  color: #909399;
  flex-shrink: 0;
  margin-top: 2px;
}

.task-summary {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.task-badges {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
}

.task-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #c0c4cc;
}

.detail-panel {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  overflow-y: auto;
  height: calc(100vh - 260px);
}

.detail-header {
  margin-bottom: 16px;
}

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.detail-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.detail-meta {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: #909399;
}

.changed-fields {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.fields-label {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}

.comparison-row {
  margin-bottom: 20px;
}

.comparison-panel {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
}

.panel-header {
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}

.before-panel .panel-header {
  background: #fef0f0;
  color: #f56c6c;
}

.after-panel .panel-header {
  background: #f0f9eb;
  color: #67c23a;
}

.comparison-body {
  padding: 12px 14px;
}

.field-row {
  display: flex;
  padding: 6px 0;
  border-bottom: 1px solid #f5f5f5;
}

.field-row:last-child {
  border-bottom: none;
}

.field-name {
  width: 100px;
  flex-shrink: 0;
  font-size: 12px;
  color: #909399;
  font-weight: 500;
}

.field-value {
  font-size: 13px;
  color: #303133;
  word-break: break-all;
}

.before-value {
  background: #fef0f0;
  padding: 2px 6px;
  border-radius: 3px;
}

.after-value {
  background: #f0f9eb;
  padding: 2px 6px;
  border-radius: 3px;
}

.action-bar {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}
</style>
