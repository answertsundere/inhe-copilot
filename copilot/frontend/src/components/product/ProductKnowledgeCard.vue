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
  return p.value.status === 'pending_review' ? 1 : 0
})
const riskCount = computed(() => p.value.high_risk_qa_count || 0)

const updateTime = computed(() => formatDateTime(p.value.updated_at))
const categoryText = computed(() => {
  const parts = [p.value.category_l1, p.value.category_l2, p.value.category_l3].filter(Boolean)
  return parts.join(' / ') || '-'
})

const categoryFirstChar = computed(() => {
  return (p.value.category_l1 || p.value.product_name || '?').charAt(0)
})

const coverSourceLabel = computed(() => {
  const map: Record<string, string> = {
    appearance_image: '外观图',
    size_image: '尺寸图',
    install_image: '安装图',
    install_video: '安装视频',
  }
  return map[p.value.cover_image_source || ''] || '商品素材'
})

const heroGradient = computed(() => {
  // 根据等级生成柔和渐变背景，与等级徽章颜色呼应
  const c = gradeColor.value
  return {
    background: `linear-gradient(135deg, ${c}35 0%, ${c}15 55%, transparent 100%)`,
  }
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

function onImageError(e: Event) {
  // 图片加载失败时隐藏 img，让占位显示
  const img = e.target as HTMLImageElement
  img.style.display = 'none'
}

function onMoreCommand(command: string) {
  if (command === 'review') {
    emit('review', p.value.id)
  } else if (command === 'retest') {
    emit('retest', p.value.id)
  }
}
</script>

<template>
  <div
    class="product-card"
    :class="[`grade-${grade.toLowerCase()}`, { 'is-risk': statusInfo.type === 'danger' }]"
    @click="onCardClick"
  >
    <!-- 顶部视觉区：主图 + 等级徽章 + 状态 -->
    <div class="card-hero" :style="heroGradient">
      <div class="hero-shine" />
      <div class="grade-badge" :style="{ background: gradeColor, boxShadow: `0 4px 12px ${gradeColor}66` }">
        <span class="grade-text">{{ grade }}</span>
      </div>
      <div class="hero-status">
        <el-tag :type="statusInfo.type" size="small" effect="dark" round>{{ statusInfo.label }}</el-tag>
        <el-tag v-if="agentStatus.type === 'success'" type="success" size="small" effect="dark" round>
          {{ agentStatus.label }}
        </el-tag>
      </div>

      <div class="hero-image-wrap">
        <img
          v-if="p.cover_image_url"
          :src="p.cover_image_url"
          class="hero-image"
          alt=""
          @error="onImageError"
        />
        <div v-else class="hero-placeholder">
          <div class="placeholder-char">{{ categoryFirstChar }}</div>
          <el-icon :size="28"><Picture /></el-icon>
          <div class="placeholder-hint">
            {{ p.media_count ? '素材未选为封面' : '待补素材' }}
          </div>
        </div>
      </div>

      <div v-if="p.cover_image_url" class="image-source-tag">
        {{ coverSourceLabel }}
      </div>
    </div>

    <!-- 商品信息 -->
    <div class="card-body">
      <div class="product-name" :title="displayName">{{ displayName }}</div>
      <div class="product-meta">
        <span class="product-sku" :title="p.i_id">{{ p.i_id }}</span>
        <span class="meta-dot">·</span>
        <span class="product-cat" :title="categoryText">{{ categoryText }}</span>
      </div>

      <!-- 完整度大数字 -->
      <div class="completeness-wrap">
        <div class="completeness-main">
          <span class="completeness-score" :style="{ color: completenessColor }">
            {{ p.completeness_score || 0 }}
          </span>
          <span class="completeness-unit">%</span>
        </div>
        <el-progress
          :percentage="p.completeness_score || 0"
          :stroke-width="8"
          :color="completenessColor"
          :show-text="false"
          class="completeness-bar"
        />
      </div>

      <!-- 任务指标 -->
      <div class="task-row">
        <div class="task-item" :class="{ active: pendingFillCount > 0 }">
          <span class="task-value">{{ pendingFillCount }}</span>
          <span class="task-label">待补</span>
        </div>
        <div class="task-item" :class="{ active: pendingReviewCount > 0 }">
          <span class="task-value">{{ pendingReviewCount }}</span>
          <span class="task-label">待审</span>
        </div>
        <div class="task-item" :class="{ active: riskCount > 0 }">
          <span class="task-value">{{ riskCount }}</span>
          <span class="task-label">风险</span>
        </div>
        <div class="task-item media-count">
          <span class="task-value">{{ p.media_count || 0 }}</span>
          <span class="task-label">素材</span>
        </div>
      </div>

      <!-- 缺口标签 -->
      <div v-if="gapTags.length" class="gap-row">
        <span
          v-for="tag in gapTags.slice(0, 2)"
          :key="tag.text"
          class="gap-pill"
          :class="`gap-${tag.type}`"
        >
          {{ tag.text }}
        </span>
        <span v-if="gapTags.length > 2" class="gap-more">+{{ gapTags.length - 2 }}</span>
      </div>
    </div>

    <!-- 底部操作 -->
    <div class="card-footer">
      <el-button size="small" :icon="Edit" @click="onFill">填写</el-button>
      <el-button size="small" :icon="View" @click="onCardClick">查看</el-button>
      <el-dropdown trigger="click" size="small" @click.stop @command="onMoreCommand">
        <el-button size="small" :icon="Upload" @click.stop>
          更多
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="review" :disabled="p.status !== 'draft'">
              <el-icon><Upload /></el-icon> 提交审核
            </el-dropdown-item>
            <el-dropdown-item command="retest">
              <el-icon><RefreshRight /></el-icon> 复测 Agent
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div class="update-tip">最近更新 {{ updateTime }}</div>
  </div>
</template>

<style scoped lang="scss">
.product-card {
  position: relative;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  overflow: hidden;
  box-shadow: var(--kb-shadow-card);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
  cursor: pointer;
  display: flex;
  flex-direction: column;
}

.product-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06);
}

.product-card.is-risk {
  border-color: rgba(239, 68, 68, 0.35);
}

/* 顶部视觉区 */
.card-hero {
  position: relative;
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-bottom: 1px solid var(--kb-border);
}

.hero-shine {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.22) 0%, transparent 45%, rgba(255, 255, 255, 0.08) 100%);
  pointer-events: none;
}

.grade-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  width: 36px;
  height: 42px;
  clip-path: polygon(50% 0%, 100% 20%, 100% 80%, 50% 100%, 0% 80%, 0% 20%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
}

.grade-text {
  color: #fff;
  font-size: 18px;
  font-weight: 900;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
  margin-top: -2px;
}

.hero-status {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  z-index: 2;
}

.hero-image-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hero-image {
  position: relative;
  z-index: 2;
  max-width: 92%;
  max-height: 86%;
  object-fit: contain;
  padding: 6px;
  border-radius: var(--kb-radius-md);
  background: rgba(255, 255, 255, 0.35);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  transition: transform 0.35s ease, box-shadow 0.35s ease;
}

.product-card:hover .hero-image {
  transform: scale(1.05);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
}

.hero-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--kb-text-tertiary);
}

.placeholder-char {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--kb-bg-hover) 0%, var(--kb-border) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 700;
  color: var(--kb-text-secondary);
  border: 2px solid var(--kb-border);
}

.placeholder-hint {
  font-size: 12px;
  color: var(--kb-text-tertiary);
}

.image-source-tag {
  position: absolute;
  bottom: 8px;
  left: 10px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  backdrop-filter: blur(4px);
  z-index: 2;
}

/* 卡片主体 */
.card-body {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}

.product-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--kb-text-primary);
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 40px;
}

.product-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--kb-text-secondary);
  overflow: hidden;
}

.product-sku {
  font-family: 'SF Mono', 'Sarasa Mono SC', 'Noto Sans Mono CJK SC', 'Microsoft YaHei Mono', monospace;
  flex-shrink: 0;
  max-width: 45%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-dot {
  color: var(--kb-text-tertiary);
}

.product-cat {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 完整度 */
.completeness-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.completeness-main {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.completeness-score {
  font-size: 28px;
  font-weight: 900;
  line-height: 1;
}

.completeness-unit {
  font-size: 14px;
  font-weight: 700;
  color: var(--kb-text-secondary);
}

.completeness-bar {
  width: 100%;
}

.completeness-bar :deep(.el-progress-bar__outer) {
  border-radius: 4px;
  background-color: var(--kb-bg-hover);
}

.completeness-bar :deep(.el-progress-bar__inner) {
  border-radius: 4px;
}

/* 让商品图从背景中凸显出来的舞台光 */
.hero-image-wrap::before {
  content: '';
  position: absolute;
  width: 70%;
  height: 60%;
  background: radial-gradient(ellipse at center, rgba(255, 255, 255, 0.55) 0%, rgba(255, 255, 255, 0) 70%);
  pointer-events: none;
  z-index: 1;
}

/* 任务指标 */
.task-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.task-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 4px;
  border-radius: var(--kb-radius-md);
  background: var(--kb-bg-hover);
  transition: background 0.2s ease;
}

.task-item.active {
  background: rgba(245, 158, 11, 0.12);
}

.task-item.active .task-value {
  color: var(--el-color-warning);
}

.task-value {
  font-size: 15px;
  font-weight: 800;
  color: var(--kb-text-primary);
  line-height: 1.1;
}

.task-label {
  font-size: 11px;
  color: var(--kb-text-secondary);
}

/* 缺口标签 */
.gap-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 22px;
}

.gap-pill {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 12px;
  font-weight: 600;
}

.gap-warning {
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
}

.gap-danger {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
}

.gap-info {
  background: rgba(59, 130, 246, 0.1);
  color: #2563eb;
}

.gap-more {
  font-size: 11px;
  color: var(--kb-text-tertiary);
}

/* 底部操作 */
.card-footer {
  display: flex;
  gap: 8px;
  padding: 0 14px 12px;
}

.card-footer .el-button {
  flex: 1;
  min-width: 0;
}

.update-tip {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  text-align: right;
  padding: 0 14px 12px;
  margin-top: -8px;
}
</style>
