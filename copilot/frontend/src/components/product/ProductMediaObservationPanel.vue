<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getProductMediaObservations, reviewProductMediaObservation } from '../../api/product'
import { useCurrentUser } from '../../composables/useCurrentUser'

const props = withDefaults(defineProps<{ product?: any; queueMode?: boolean }>(), { queueMode: false })
const router = useRouter()
const { canAudit } = useCurrentUser()
const loading = ref(false)
const rows = ref<any[]>([])

const productId = computed(() => props.product?.i_id || '')
const title = computed(() => props.queueMode ? 'AI 视觉观察审核队列' : 'AI 视觉观察（Shadow）')
const emptyDescription = computed(() => props.queueMode ? '当前没有待审核的 AI 视觉观察' : '当前商品没有 AI 视觉观察候选')

const statusLabels: Record<string, string> = {
  pending_review: '待审核',
  approved_shadow: '已采用（Shadow）',
  rejected: '已拒绝',
  invalidated: '已失效',
  superseded: '已替代',
}
const typeLabels: Record<string, string> = {
  labelled_dimension: '图片标注尺寸',
  visible_text: '图片可见文字',
  visible_structure: '图片可见结构',
  layer_count: '可见层数',
  compartment_count: '可见格数',
}
const attributeLabels: Record<string, string> = {
  width: '宽度',
  height: '高度',
  depth: '深度',
  length: '长度',
  layer_count: '层数',
  compartment_count: '格数',
  visible_text: '可见文字',
  visible_structure: '可见结构',
  shelf_layout: '层板结构',
  open_compartment: '开放格结构',
  door_layout: '柜门结构',
  drawer_layout: '抽屉结构',
  partition_layout: '隔板结构',
}
const valueLabels: Record<string, string> = {
  'two-step structure': '两级结构',
}

function statusLabel(value: string) {
  return statusLabels[value] || value || '未知'
}

function typeLabel(value: string) {
  return typeLabels[value] || value || '未分类'
}

function attributeLabel(value: string) {
  return attributeLabels[value] || value || '未分类'
}

function observationValue(row: any) {
  const value = String(row.raw_observation || '').trim()
  return valueLabels[value.toLowerCase()] || value || '未识别到内容'
}

function reviewPrompt(row: any) {
  const value = observationValue(row)
  if (row.observation_type === 'labelled_dimension') {
    return `核对图片是否明确标注“${attributeLabel(row.attribute_key)} ${value}”`
  }
  if (row.observation_type === 'layer_count') return `数一下图片中的可见层数是否为 ${value}`
  if (row.observation_type === 'compartment_count') return `数一下图片中的可见格数是否为 ${value}`
  if (row.observation_type === 'visible_structure') return `核对图片展示的结构是否确实为“${value}”`
  return `核对图片中是否清楚出现文字“${value}”`
}

async function load() {
  if (!props.queueMode && !productId.value) return
  loading.value = true
  try {
    const params = props.queueMode ? { status: 'pending_review' } : { i_id: productId.value }
    const { data } = await getProductMediaObservations(params)
    rows.value = data.items || []
  } catch {
    ElMessage.error('加载 AI 视觉观察失败')
  } finally {
    loading.value = false
  }
}

async function action(row: any, type: 'approve' | 'reject') {
  if (!canAudit.value || row.status !== 'pending_review') return
  const label = type === 'approve' ? '采用 Shadow 观察' : '拒绝观察'
  try {
    const { value } = await ElMessageBox.prompt('填写审核原因', label, {
      inputPattern: /\S+/,
      inputErrorMessage: '审核原因必填',
    })
    await reviewProductMediaObservation(row.id, type, { version: row.version, reason: value })
    ElMessage.success('审核记录已保存，未写入正式知识库')
    await load()
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.response?.data?.error || '审核操作失败')
    }
  }
}

async function editAndApprove(row: any) {
  if (!canAudit.value || row.status !== 'pending_review') return
  try {
    const { value } = await ElMessageBox.prompt('确认或修正观察内容', '修改后采用 Shadow 观察', {
      inputValue: row.raw_observation,
      inputPattern: /\S+/,
      inputErrorMessage: '观察内容必填',
    })
    const { value: reason } = await ElMessageBox.prompt('填写审核原因', '修改后采用 Shadow 观察', {
      inputPattern: /\S+/,
      inputErrorMessage: '审核原因必填',
    })
    await reviewProductMediaObservation(row.id, 'approve', {
      version: row.version,
      reason,
      edits: { reviewed_raw_observation: value },
    })
    ElMessage.success('审核记录已保存，未写入正式知识库')
    await load()
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.response?.data?.error || '审核操作失败')
    }
  }
}

function openReviewQueue() {
  router.push('/media-observation-review')
}

watch(productId, load, { immediate: true })
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="observation-panel">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      :title="title"
      description="这是离线模型候选，未写入正式商品知识，也不会影响客服回复或自动发送。审核时请以来源图片为准。"
    />
    <div class="review-guide">
      <strong>你只需要核对三件事：</strong>
      <span>① 图片是不是这个商品；② 图片上是否真的有对应尺寸、文字、层数或结构；③ 观察值是否抄对。</span>
      <span>完全正确点“采用”，内容基本正确但表述有误点“修改后采用”，看不清或不一致点“拒绝”。</span>
      <span class="risk-note">不要采用承重、安全、无毒、儿童适用、认证或安装处方等高风险推断。</span>
    </div>
    <div v-if="!queueMode" class="queue-link-row">
      <span>当前商品没有候选时，可在集中队列审核其他商品。</span>
      <el-button link type="primary" @click="openReviewQueue">打开集中审核队列</el-button>
    </div>
    <el-empty v-if="!rows.length && !loading" :description="emptyDescription" />
    <el-table v-else :data="rows" size="small" class="observation-table">
      <el-table-column v-if="queueMode" label="商品" min-width="150">
        <template #default="{ row }">
          <div>{{ row.source_media?.product_name || row.i_id }}</div>
          <small>{{ row.i_id }}</small>
        </template>
      </el-table-column>
      <el-table-column label="来源图片" width="104">
        <template #default="{ row }">
          <el-image
            v-if="row.source_media?.asset_url"
            :src="row.source_media.asset_url"
            :preview-src-list="[row.source_media.asset_url]"
            fit="cover"
            class="media-preview"
            preview-teleported
          />
          <span v-else class="readonly">无预览</span>
        </template>
      </el-table-column>
      <el-table-column label="识别内容" min-width="135">
        <template #default="{ row }">
          <div>{{ typeLabel(row.observation_type) }}</div>
          <small>{{ attributeLabel(row.attribute_key) }}</small>
        </template>
      </el-table-column>
      <el-table-column label="模型观察值" min-width="180">
        <template #default="{ row }">
          <div>{{ observationValue(row) }}</div>
          <small>模型置信度 {{ Math.round((row.confidence || 0) * 100) }}% · {{ statusLabel(row.status) }}</small>
        </template>
      </el-table-column>
      <el-table-column label="你要核对什么" min-width="285">
        <template #default="{ row }">{{ reviewPrompt(row) }}</template>
      </el-table-column>
      <el-table-column v-if="canAudit" label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'pending_review' && row.risk_class === 'low' && !row.conflict_status">
            <el-button link type="primary" @click="action(row, 'approve')">采用</el-button>
            <el-button link type="primary" @click="editAndApprove(row)">修改后采用</el-button>
            <el-button link type="danger" @click="action(row, 'reject')">拒绝</el-button>
          </template>
          <span v-else class="readonly">只读</span>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<style scoped lang="scss">
.observation-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.queue-link-row { display: flex; align-items: center; gap: 4px; color: var(--kb-text-secondary); font-size: 13px; }
.review-guide { display: grid; gap: 5px; padding: 12px 14px; border: 1px solid var(--kb-border); background: var(--kb-bg-soft, #f7f8fa); font-size: 13px; line-height: 1.6; }
.risk-note { color: var(--el-color-danger); }
.observation-table { width: 100%; }
.media-preview { width: 72px; height: 56px; border-radius: 4px; border: 1px solid var(--kb-border); cursor: zoom-in; }
.hash, .readonly { color: var(--kb-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
small { color: var(--kb-text-secondary); font-size: 12px; }
@media (max-width: 760px) { .observation-table { min-width: 900px; } .observation-panel { overflow-x: auto; } }
</style>
