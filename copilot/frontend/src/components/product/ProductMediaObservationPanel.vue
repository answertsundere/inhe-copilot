<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getProductMediaObservations, reviewProductMediaObservation } from '../../api/product'
import { useCurrentUser } from '../../composables/useCurrentUser'

const props = defineProps<{ product: any }>()
const { canAudit } = useCurrentUser()
const loading = ref(false)
const rows = ref<any[]>([])

const productId = computed(() => props.product?.i_id || '')
async function load() {
  if (!productId.value) return
  loading.value = true
  try {
    const { data } = await getProductMediaObservations({ i_id: productId.value })
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

watch(productId, load, { immediate: true })
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="observation-panel">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="AI 视觉观察（Shadow）"
      description="这是离线模型候选，未写入正式商品知识，也不会影响客服回复或自动发送。"
    />
    <el-empty v-if="!rows.length && !loading" description="当前商品暂无待审核的 AI 视觉观察" />
    <el-table v-else :data="rows" size="small" class="observation-table">
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
.observation-table { width: 100%; }
.hash, .readonly { color: var(--kb-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
@media (max-width: 760px) { .observation-table { min-width: 720px; } .observation-panel { overflow-x: auto; } }
</style>
