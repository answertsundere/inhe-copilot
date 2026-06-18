<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getProductVersions } from '../../api/product'
import { getReviews } from '../../api/review'

const props = defineProps<{
  product: any
}>()

const loading = ref(false)
const versions = ref<any[]>([])
const reviews = ref<any[]>([])

async function fetchData() {
  if (!props.product?.id) return
  loading.value = true
  try {
    const [versionsRes, reviewsRes] = await Promise.allSettled([
      getProductVersions(props.product.id),
      getReviews({ target_type: 'kb_product', target_id: props.product.id, limit: 50 }),
    ])
    versions.value = versionsRes.status === 'fulfilled' ? versionsRes.value.data.items || [] : []
    reviews.value = reviewsRes.status === 'fulfilled' ? reviewsRes.value.data.items || [] : []
  } catch {
    ElMessage.warning('加载审核记录失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)

const timeline = computed(() => {
  const items: any[] = []
  versions.value.forEach((v) => {
    items.push({
      type: 'version',
      timestamp: v.created_at,
      title: `商品${v.action}`,
      content: v.performed_by ? `由 ${v.performed_by} 操作` : '',
      detail: v.changed_fields?.length ? `变更字段：${v.changed_fields.join('、')}` : '',
      status: v.after_status,
    })
  })
  reviews.value.forEach((r) => {
    items.push({
      type: 'review',
      timestamp: r.created_at,
      title: `审核任务：${r.change_summary || '提交审核'}`,
      content: `申请人：${r.requested_by || '-'}；审核人：${r.reviewer || '待审核'}`,
      detail: r.review_opinion || '',
      status: r.status,
    })
  })
  return items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
})

function getStatusType(status: string) {
  if (status === 'published' || status === 'approved') return 'success'
  if (status === 'pending_review' || status === 'pending') return 'warning'
  if (status === 'rejected') return 'danger'
  if (status === 'draft') return 'info'
  return 'info'
}

function formatTime(d: string) {
  if (!d) return '-'
  try {
    return new Date(d).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return d
  }
}

function rollback(version: any) {
  ElMessage.info('版本回退功能需主管确认后执行，后续对接版本回退接口')
}
</script>

<template>
  <div v-loading="loading" class="audit-panel">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="审核与版本"
      description="展示商品修改记录、审核任务和版本变更。版本回退入口仅主管可见。"
      style="margin-bottom: 16px"
    />

    <div v-if="timeline.length" class="timeline-list">
      <div v-for="item in timeline" :key="item.timestamp + item.type" class="timeline-item">
        <div class="timeline-marker" :class="`status-${getStatusType(item.status)}`"></div>
        <div class="timeline-content">
          <div class="timeline-header">
            <span class="timeline-title">{{ item.title }}</span>
            <el-tag size="small" :type="getStatusType(item.status) as any">{{ item.status }}</el-tag>
          </div>
          <div class="timeline-body">
            <div class="timeline-meta">{{ item.content }}</div>
            <div v-if="item.detail" class="timeline-detail">{{ item.detail }}</div>
          </div>
          <div class="timeline-time">{{ formatTime(item.timestamp) }}</div>
        </div>
      </div>
    </div>

    <el-empty v-else description="暂无审核与版本记录。" />
  </div>
</template>

<style scoped lang="scss">
.audit-panel {
  padding: 4px;
}
.timeline-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
}
.timeline-list::before {
  content: '';
  position: absolute;
  left: 9px;
  top: 6px;
  bottom: 6px;
  width: 2px;
  background: var(--kb-border-strong);
}
.timeline-item {
  display: flex;
  gap: 14px;
  padding: 12px 0;
  position: relative;
}
.timeline-marker {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--kb-bg-card);
  border: 3px solid;
  flex-shrink: 0;
  z-index: 1;
}
.timeline-marker.status-success { border-color: var(--kb-success-text); }
.timeline-marker.status-warning { border-color: var(--kb-warning-text); }
.timeline-marker.status-danger { border-color: var(--kb-danger-text); }
.timeline-marker.status-info { border-color: var(--kb-text-tertiary); }
.timeline-content {
  flex: 1;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 12px 14px;
  box-shadow: var(--kb-shadow-card);
}
.timeline-header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}
.timeline-title {
  font-size: 14px;
  font-weight: 600;
}
.timeline-meta {
  font-size: 12px;
  color: var(--kb-text-secondary);
}
.timeline-detail {
  font-size: 12px;
  color: var(--kb-text-tertiary);
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--kb-border);
}
.timeline-time {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  margin-top: 8px;
  text-align: right;
}
</style>
