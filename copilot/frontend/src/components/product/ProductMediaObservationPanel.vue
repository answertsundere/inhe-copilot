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
      <el-table-column prop="status" label="状态" width="118">
        <template #default="{ row }">
          <el-tag :type="row.status === 'pending_review' ? 'warning' : 'info'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="observation_type" label="类型" min-width="130" />
      <el-table-column prop="attribute_key" label="属性" min-width="110" />
      <el-table-column label="观察值" min-width="180">
        <template #default="{ row }">
          <span>{{ row.raw_observation }}</span>
          <span v-if="row.normalized_value">（{{ row.normalized_value }} {{ row.normalized_unit || '' }}）</span>
        </template>
      </el-table-column>
      <el-table-column prop="confidence" label="置信度" width="90">
        <template #default="{ row }">{{ Math.round((row.confidence || 0) * 100) }}%</template>
      </el-table-column>
      <el-table-column label="Hash" min-width="160">
        <template #default="{ row }"><span class="hash">{{ row.hash_comparison_status }}</span></template>
      </el-table-column>
      <el-table-column v-if="canAudit" label="操作" width="240" fixed="right">
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
.observation-table { width: 100%; }
.media-preview { width: 72px; height: 56px; border-radius: 4px; border: 1px solid var(--kb-border); cursor: zoom-in; }
.hash, .readonly { color: var(--kb-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
small { color: var(--kb-text-secondary); font-size: 12px; }
@media (max-width: 760px) { .observation-table { min-width: 900px; } .observation-panel { overflow-x: auto; } }
</style>
