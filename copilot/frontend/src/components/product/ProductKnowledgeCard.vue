<script setup lang="ts">
import { computed } from 'vue'
import {
  Edit, View, Upload, RefreshRight, Picture,
} from '@element-plus/icons-vue'
import {
  getProductGrade,
  getGradeColor,
  getProductStatusInfo,
  getAgentStatusInfo,
  getGapTags,
  getCompletenessColor,
  formatDateTime,
  type ProductItem,
} from '../../utils/productStatus'

const props = defineProps<{
  product: ProductItem
}>()

const emit = defineEmits<{
  click: [id: number]
  fill: [id: number]
  review: [id: number]
  retest: [id: number]
}>()

const p = computed(() => props.product)

const displayName = computed(() => {
  return p.value.specs?.display_name || p.value.product_name
})

const grade = computed(() => getProductGrade(p.value))
const gradeColor = computed(() => getGradeColor(grade.value))
const statusInfo = computed(() => getProductStatusInfo(p.value))
const agentStatus = computed(() => getAgentStatusInfo(p.value))
const gapTags = computed(() => getGapTags(p.value))
const completenessColor = computed(() => getCompletenessColor(p.value.completeness_score || 0))

const pendingFillCount = computed(() => gapTags.value.filter((t) => t.text.startsWith('缺')).length)
const pendingReviewCount = computed(() => {
  let count = p.value.status === 'pending_review' ? 1 : 0
  return count
})
const rejectedCount = computed(() => 0)

const owner = computed(() => p.value.updated_by || '-')
const updateTime = computed(() => formatDateTime(p.value.updated_at))
const categoryText = computed(() => {
  const parts = [p.value.category_l1, p.value.category_l2, p.value.category_l3].filter(Boolean)
  return parts.join(' / ') || '-'
})

function onCardClick() {
  emit('click', p.value.id)
}

function onFill(e: Event) {
  e.stopPropagation()
  emit('fill', p.value.id)
}

function onReview(e: Event) {
  e.stopPropagation()
  emit('review', p.value.id)
}

function onRetest(e: Event) {
  e.stopPropagation()
  emit('retest', p.value.id)
}
</script>

<template>
  <div class="product-card" :class="{ 'is-risk': statusInfo.type === 'danger' }" @click="onCardClick">
    <div class="card-top">
      <div class="grade-badge" :style="{ background: gradeColor }">
        {{ grade }}
      </div>
      <div class="status-badges">
        <el-tag :type="statusInfo.type" size="small" effect="light">{{ statusInfo.label }}</el-tag>
        <el-tag :type="agentStatus.type" size="small" effect="light">{{ agentStatus.label }}</el-tag>
      </div>
    </div>

    <div class="card-main">
      <div class="image-wrap">
        <el-icon :size="40" class="placeholder-icon"><Picture /></el-icon>
      </div>
      <div class="info-wrap">
        <div class="product-name" :title="displayName">{{ displayName }}</div>
        <div class="product-sku">{{ p.i_id }}</div>
        <div class="product-cat">{{ categoryText }}</div>
      </div>
    </div>

    <div class="completeness-row">
      <div class="completeness-label">
        完整度 <span class="score" :style="{ color: completenessColor }">{{ p.completeness_score || 0 }}%</span>
      </div>
      <el-progress
        :percentage="p.completeness_score || 0"
        :stroke-width="6"
        :color="completenessColor"
        :show-text="false"
        class="completeness-bar"
      />
    </div>

    <div class="counts-row">
      <div class="count-item">
        <span class="count-value">{{ pendingFillCount }}</span>
        <span class="count-label">待补</span>
      </div>
      <div class="count-item">
        <span class="count-value">{{ pendingReviewCount }}</span>
        <span class="count-label">待审</span>
      </div>
      <div class="count-item">
        <span class="count-value">{{ rejectedCount }}</span>
        <span class="count-label">退回</span>
      </div>
      <div class="count-item owner">
        <span class="count-value text-secondary">{{ owner }}</span>
        <span class="count-label">负责人</span>
      </div>
    </div>

    <div class="tags-row">
      <el-tag
        v-for="tag in gapTags.slice(0, 4)"
        :key="tag.text"
        size="small"
        :type="tag.type as any"
        effect="light"
        class="gap-tag"
      >
        {{ tag.text }}
      </el-tag>
      <el-tag v-if="gapTags.length > 4" size="small" type="info" effect="light" class="gap-tag">
        +{{ gapTags.length - 4 }}
      </el-tag>
    </div>

    <div class="update-row">
      <span>最近更新 {{ updateTime }}</span>
    </div>

    <div class="actions-row">
      <el-button size="small" :icon="Edit" @click="onFill">填写</el-button>
      <el-button size="small" :icon="View" @click="onCardClick">查看</el-button>
      <el-button size="small" type="warning" :icon="Upload" :disabled="p.status !== 'draft'" @click="onReview">
        提交审核
      </el-button>
      <el-button size="small" type="info" :icon="RefreshRight" @click="onRetest">
        复测 Agent
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.product-card {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px;
  box-shadow: var(--kb-shadow-card);
  transition: all 0.2s ease;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.product-card:hover {
  box-shadow: var(--kb-shadow-card-hover);
  transform: translateY(-2px);
}

.product-card.is-risk {
  border-color: rgba(239, 68, 68, 0.4);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.grade-badge {
  width: 28px;
  height: 28px;
  border-radius: var(--kb-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.status-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
}

.card-main {
  display: flex;
  gap: 10px;
}

.image-wrap {
  width: 72px;
  height: 72px;
  border-radius: var(--kb-radius-md);
  background: var(--kb-bg-hover);
  border: 1px solid var(--kb-border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.placeholder-icon {
  color: var(--kb-text-tertiary);
}

.info-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.product-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--kb-text-primary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.product-sku {
  font-size: 12px;
  color: var(--kb-text-secondary);
  font-family: 'SF Mono', 'Sarasa Mono SC', 'Noto Sans Mono CJK SC', 'Microsoft YaHei Mono', monospace;
}

.product-cat {
  font-size: 12px;
  color: var(--kb-text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.completeness-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.completeness-label {
  font-size: 12px;
  color: var(--kb-text-secondary);
}

.score {
  font-weight: 600;
}

.completeness-bar {
  width: 100%;
}

.counts-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}

.count-item {
  background: var(--kb-bg-hover);
  border-radius: var(--kb-radius-md);
  padding: 6px 4px;
  text-align: center;
}

.count-value {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: var(--kb-text-primary);
  line-height: 1.2;
}

.count-label {
  display: block;
  font-size: 11px;
  color: var(--kb-text-secondary);
  margin-top: 2px;
}

.text-secondary {
  color: var(--kb-text-secondary);
  font-weight: 500;
  font-size: 12px;
}

.tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 22px;
}

.gap-tag {
  font-size: 11px;
}

.update-row {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  text-align: right;
}

.actions-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-top: 1px solid var(--kb-border);
  padding-top: 10px;
}

.actions-row .el-button {
  flex: 1;
  min-width: 0;
  padding-left: 6px;
  padding-right: 6px;
}

.actions-row .el-button + .el-button {
  margin-left: 0;
}
</style>
