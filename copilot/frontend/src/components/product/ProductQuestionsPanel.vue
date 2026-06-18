<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProductQA,
  createProductQA,
  unlinkProductQA,
  linkProductQA,
} from '../../api/product'
import { getQAList, updateQA, deleteQA } from '../../api/qa'
import StatusTag from '../common/StatusTag.vue'
import RiskBadge from '../common/RiskBadge.vue'
import { useCurrentUser } from '../../composables/useCurrentUser'

const props = defineProps<{
  product: any
}>()

const emit = defineEmits<{
  refreshed: []
}>()

const { canEdit } = useCurrentUser()
const loading = ref(false)
const qaList = ref<any[]>([])
const search = ref('')
const riskFilter = ref('')

const filteredQA = computed(() => {
  let list = qaList.value
  if (search.value) {
    const kw = search.value.toLowerCase()
    list = list.filter((q) =>
      (q.question || '').toLowerCase().includes(kw) ||
      (q.answer || '').toLowerCase().includes(kw)
    )
  }
  if (riskFilter.value) list = list.filter((q) => q.risk_level === riskFilter.value)
  return list
})

async function fetchQA() {
  if (!props.product?.id) return
  loading.value = true
  try {
    const { data } = await getProductQA(props.product.id)
    qaList.value = data.items || []
  } catch {
    qaList.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchQA)

const createDialogVisible = ref(false)
const createForm = ref({
  question: '',
  answer: '',
  intent: 'general',
  risk_level: 'low',
  auto_reply: true,
})

async function saveCreate() {
  if (!props.product?.id) return
  if (!createForm.value.question.trim() || !createForm.value.answer.trim()) {
    ElMessage.warning('请填写问题和答案')
    return
  }
  try {
    await createProductQA(props.product.id, { ...createForm.value })
    ElMessage.success('问答已创建并关联')
    createDialogVisible.value = false
    createForm.value = { question: '', answer: '', intent: 'general', risk_level: 'low', auto_reply: true }
    await fetchQA()
    emit('refreshed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '创建失败')
  }
}

async function unlinkQA(qa: any) {
  if (!props.product?.id) return
  try {
    await ElMessageBox.confirm('取消关联后该问答不再归属当前商品，是否继续？', '提示', { type: 'warning' })
    await unlinkProductQA(props.product.id, qa.id)
    ElMessage.success('已取消关联')
    await fetchQA()
    emit('refreshed')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '取消关联失败')
  }
}

async function removeQA(qa: any) {
  try {
    await ElMessageBox.confirm('删除后不可恢复，是否继续？', '删除问答', { type: 'warning' })
    await deleteQA(qa.id)
    ElMessage.success('已删除')
    await fetchQA()
    emit('refreshed')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '删除失败')
  }
}

const linkDialogVisible = ref(false)
const linkSearch = ref('')
const linkCandidates = ref<any[]>([])
const linkLoading = ref(false)

async function searchCandidates() {
  linkLoading.value = true
  try {
    const params: Record<string, any> = { limit: 50, status: '' }
    if (linkSearch.value) params.search = linkSearch.value
    const { data } = await getQAList(params)
    const linkedIds = new Set(qaList.value.map((q) => q.id))
    linkCandidates.value = (data.items || []).filter((q: any) => !linkedIds.has(q.id))
  } catch {
    linkCandidates.value = []
  } finally {
    linkLoading.value = false
  }
}

async function openLinkDialog() {
  linkDialogVisible.value = true
  linkSearch.value = ''
  linkCandidates.value = []
  await searchCandidates()
}

async function confirmLink(qa: any) {
  if (!props.product?.id) return
  try {
    await linkProductQA(props.product.id, qa.id)
    ElMessage.success('关联问法成功')
    await fetchQA()
    await searchCandidates()
    emit('refreshed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '关联失败')
  }
}

function getSourceLabel(source: string) {
  if (source === 'training_sample') return '训练样本'
  if (source === 'manual') return '人工新增'
  if (source === 'error_feedback') return '错误反馈'
  if (source === 'faq') return 'FAQ'
  return source || '其他'
}
</script>

<template>
  <div v-loading="loading" class="questions-panel">
    <div class="panel-toolbar">
      <el-input v-model="search" placeholder="搜索客户原话/答案" clearable size="small" style="width: 220px" />
      <el-select v-model="riskFilter" placeholder="风险等级" clearable size="small" style="width: 110px">
        <el-option label="低" value="low" />
        <el-option label="中" value="medium" />
        <el-option label="高" value="high" />
        <el-option label="极高" value="critical" />
      </el-select>
      <div style="flex: 1"></div>
      <el-button size="small" type="primary" :disabled="!canEdit" @click="createDialogVisible = true">新增问法</el-button>
      <el-button size="small" @click="openLinkDialog">关联已有问法</el-button>
      <span class="count-text">共 {{ filteredQA.length }} 条</span>
    </div>

    <div v-if="filteredQA.length" class="question-list">
      <div v-for="qa in filteredQA" :key="qa.id" class="question-card">
        <div class="question-header">
          <div class="question-text">{{ qa.question }}</div>
          <div class="question-badges">
            <RiskBadge :level="qa.risk_level" />
            <StatusTag :status="qa.status" />
            <el-tag v-if="qa.product_id === product?.id" size="small" type="success">当前商品</el-tag>
            <el-tag v-else size="small" type="warning">类目通用</el-tag>
          </div>
        </div>
        <div class="question-answer">{{ qa.answer }}</div>
        <div class="question-meta">
          <span>意图：{{ qa.intent || '-' }}</span>
          <span>来源：{{ getSourceLabel(qa.source_type) }}</span>
          <span>自动回复：{{ qa.auto_reply ? '允许' : '禁止' }}</span>
          <span>更新：{{ qa.updated_by || '-' }} {{ qa.updated_at?.replace('T', ' ').slice(0, 16) }}</span>
        </div>
        <div class="question-actions">
          <el-button size="small" text type="danger" :disabled="!canEdit" @click="unlinkQA(qa)">
            取消关联
          </el-button>
          <el-button size="small" text type="danger" :disabled="!canEdit" @click="removeQA(qa)">
            删除
          </el-button>
        </div>
      </div>
    </div>

    <el-empty v-else description="暂无客户问法。可以新增或关联已有问答。" />

    <el-dialog v-model="createDialogVisible" title="新增客户问法" width="640px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="客户原话">
          <el-input v-model="createForm.question" type="textarea" :rows="2" placeholder="客户可能会怎么问" />
        </el-form-item>
        <el-form-item label="推荐回答">
          <el-input v-model="createForm.answer" type="textarea" :rows="4" placeholder="建议回答内容" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="意图">
              <el-input v-model="createForm.intent" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="风险等级">
              <el-select v-model="createForm.risk_level" style="width: 100%">
                <el-option label="低" value="low" />
                <el-option label="中" value="medium" />
                <el-option label="高" value="high" />
                <el-option label="极高" value="critical" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-checkbox v-model="createForm.auto_reply">允许自动回复</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="createDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" :disabled="!canEdit" @click="saveCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="linkDialogVisible" title="关联已有问法" width="720px" destroy-on-close>
      <div style="display: flex; gap: 8px; margin-bottom: 12px">
        <el-input v-model="linkSearch" placeholder="搜索问题/答案" clearable size="small" @keyup.enter="searchCandidates" />
        <el-button size="small" @click="searchCandidates">搜索</el-button>
      </div>
      <el-table :data="linkCandidates" size="small" stripe v-loading="linkLoading" height="360">
        <el-table-column label="客户问题" prop="question" min-width="180" show-overflow-tooltip />
        <el-table-column label="答案摘要" min-width="160">
          <template #default="{ row }">{{ (row.answer || '').slice(0, 60) }}{{ (row.answer || '').length > 60 ? '...' : '' }}</template>
        </el-table-column>
        <el-table-column label="风险" width="70"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }"><el-button size="small" type="primary" @click="confirmLink(row)">关联</el-button></template>
        </el-table-column>
      </el-table>
      <template #footer><el-button size="small" @click="linkDialogVisible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.questions-panel {
  padding: 4px;
}
.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.count-text {
  font-size: 12px;
  color: var(--kb-text-secondary);
}
.question-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.question-card {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px;
  box-shadow: var(--kb-shadow-card);
}
.question-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.question-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--kb-text-primary);
  flex: 1;
}
.question-badges {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.question-answer {
  font-size: 13px;
  color: var(--kb-text-secondary);
  line-height: 1.6;
  margin-bottom: 10px;
  white-space: pre-wrap;
  word-break: break-word;
}
.question-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--kb-text-tertiary);
  margin-bottom: 8px;
}
.question-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
