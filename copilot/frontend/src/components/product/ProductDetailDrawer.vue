<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  submitProductReview,
  publishProduct,
  getProductHealth,
  getProductQA,
} from '../../api/product'
import {
  getProductGrade,
  getGradeColor,
  getAgentStatusInfo,
  getCompletenessColor,
  formatDateTime,
} from '../../utils/productStatus'
import { useCurrentUser } from '../../composables/useCurrentUser'
import ProductBasicPanel from './ProductBasicPanel.vue'
import ProductFactsPanel from './ProductFactsPanel.vue'
import ProductMediaPanel from './ProductMediaPanel.vue'
import ProductMediaObservationPanel from './ProductMediaObservationPanel.vue'
import ProductQuestionsPanel from './ProductQuestionsPanel.vue'
import ProductActivityPanel from './ProductActivityPanel.vue'
import ProductAgentTestPanel from './ProductAgentTestPanel.vue'
import ProductAuditTimeline from './ProductAuditTimeline.vue'

const props = defineProps<{
  modelValue: boolean
  product: any
}>()

const emit = defineEmits<{
  'update:modelValue': [val: boolean]
  saved: [product: any]
  review: [id: number]
  publish: [id: number]
}>()

const { canAudit } = useCurrentUser()

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const activeTab = ref('basic')
const loading = ref(false)
const health = ref<any>(null)
const qaList = ref<any[]>([])

const product = computed(() => props.product)
const completenessScore = computed(() => Math.round(product.value?.completeness_score || 0))
const completenessColor = computed(() => getCompletenessColor(completenessScore.value))
const agentStatus = computed(() => getAgentStatusInfo(product.value))
const grade = computed(() => getProductGrade(product.value))
const gradeColor = computed(() => getGradeColor(grade.value))

const categoryText = computed(() => {
  const parts = [product.value?.category_l1, product.value?.category_l2, product.value?.category_l3].filter(Boolean)
  return parts.join(' / ') || '-'
})

async function loadHealth() {
  if (!product.value?.id) return
  try {
    const { data } = await getProductHealth(product.value.id)
    health.value = data
  } catch {
    health.value = null
  }
}

async function loadQA() {
  if (!product.value?.id) return
  try {
    const { data } = await getProductQA(product.value.id)
    qaList.value = data.items || []
  } catch {
    qaList.value = []
  }
}

watch(() => props.product, () => {
  if (props.product) {
    loadHealth()
    loadQA()
  }
}, { immediate: true })

async function handleSubmitReview() {
  if (!product.value?.id) return
  try {
    await submitProductReview(product.value.id)
    ElMessage.success('已提交审核')
    emit('review', product.value.id)
  } catch {
    ElMessage.error('提交审核失败')
  }
}

async function handlePublish() {
  if (!product.value?.id) return
  if (!canAudit.value) {
    ElMessage.warning('仅主管/管理员可发布')
    return
  }
  try {
    await ElMessageBox.confirm('确认发布此商品？发布后将可供 Agent 使用。', '确认发布')
  } catch {
    return
  }
  try {
    await publishProduct(product.value.id)
    ElMessage.success('已发布')
    emit('publish', product.value.id)
  } catch {
    ElMessage.error('发布失败')
  }
}

function onSaved(p: any) {
  emit('saved', p)
}

function onRefreshed() {
  emit('saved', product.value)
}
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="product?.product_name || '商品详情'"
    size="80%"
    destroy-on-close
  >
    <div v-loading="loading" class="detail-drawer">
      <div class="detail-header">
        <div class="detail-meta">
          <div class="grade-pill" :style="{ background: gradeColor }">
            {{ grade }} 级
          </div>
          <el-tag :type="agentStatus.type" size="small" effect="light">{{ agentStatus.label }}</el-tag>
          <span class="meta-item">编码：{{ product?.i_id }}</span>
          <span class="meta-item">类目：{{ categoryText }}</span>
          <span class="meta-item">版本：v{{ product?.version || 1 }}</span>
          <span class="meta-item">更新：{{ formatDateTime(product?.updated_at) }}</span>
        </div>
        <div class="detail-score">
          <div class="score-num" :style="{ color: completenessColor }">{{ completenessScore }}%</div>
          <div class="score-label">完整度</div>
        </div>
      </div>

      <div class="detail-actions">
        <el-button v-if="product?.status === 'draft'" type="warning" @click="handleSubmitReview">提交审核</el-button>
        <el-button v-if="product?.status === 'pending_review'" type="success" :disabled="!canAudit" @click="handlePublish">发布</el-button>
        <el-tooltip :content="agentStatus.reason" placement="top">
          <el-tag :type="agentStatus.type" effect="dark" size="small">{{ agentStatus.label }}</el-tag>
        </el-tooltip>
      </div>

      <el-alert
        v-if="health"
        :title="health.can_agent_use ? '此商品可用于智能客服 Agent' : '此商品暂不可用于 Agent'"
        :type="health.can_agent_use ? 'success' : 'warning'"
        :description="health.agent_block_reason || agentStatus.reason"
        show-icon
        :closable="false"
        style="margin-bottom: 12px"
      />

      <el-tabs v-model="activeTab" type="border-card" class="detail-tabs">
        <el-tab-pane label="基础资料" name="basic">
          <ProductBasicPanel :product="product" :health="health" @saved="onSaved" />
        </el-tab-pane>
        <el-tab-pane label="商品事实" name="facts">
          <ProductFactsPanel :product="product" @saved="onSaved" />
        </el-tab-pane>
        <el-tab-pane label="商品素材" name="media">
          <ProductMediaPanel :product="product" @refreshed="onRefreshed" />
        </el-tab-pane>
        <el-tab-pane label="AI 视觉观察" name="media-observations">
          <ProductMediaObservationPanel :product="product" />
        </el-tab-pane>
        <el-tab-pane label="客户问法" name="questions">
          <ProductQuestionsPanel :product="product" @refreshed="onRefreshed" />
        </el-tab-pane>
        <el-tab-pane label="活动优惠" name="activity">
          <ProductActivityPanel :product="product" />
        </el-tab-pane>
        <el-tab-pane label="资料命中预检" name="agent">
          <ProductAgentTestPanel :product="product" :qa-list="qaList" />
        </el-tab-pane>
        <el-tab-pane label="审核与版本" name="audit">
          <ProductAuditTimeline :product="product" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<style scoped lang="scss">
.detail-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px 16px;
  margin-bottom: 12px;
}
.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.grade-pill {
  padding: 2px 10px;
  border-radius: var(--kb-radius-pill);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.meta-item {
  font-size: 13px;
  color: var(--kb-text-secondary);
}
.detail-score {
  text-align: center;
  flex-shrink: 0;
}
.score-num {
  font-size: 24px;
  font-weight: 800;
  line-height: 1;
}
.score-label {
  font-size: 11px;
  color: var(--kb-text-secondary);
  margin-top: 2px;
}
.detail-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.detail-tabs {
  flex: 1;
  min-height: 0;
}
.detail-tabs :deep(.el-tabs__content) {
  height: calc(100% - 40px);
  overflow-y: auto;
  padding: 12px;
}
</style>
