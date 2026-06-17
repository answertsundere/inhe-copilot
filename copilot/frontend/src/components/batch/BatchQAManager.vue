<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getQAList, createQA, updateQA, deleteQA } from '../../api/qa'
import RiskBadge from '../common/RiskBadge.vue'

const props = defineProps<{
  visible: boolean
  categoryTree: any[]
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'done'): void
}>()

const activeOp = ref<'create' | 'manage' | 'link'>('create')
const cat = reactive({ l1: '', l2: '', l3: '' })
const loading = ref(false)

const l1Options = computed(() => props.categoryTree.map((n: any) => n.label))
const l2Options = computed(() => {
  const l1 = props.categoryTree.find((n: any) => n.label === cat.l1)
  return (l1?.children || []).map((n: any) => n.label)
})
const l3Options = computed(() => {
  const l1 = props.categoryTree.find((n: any) => n.label === cat.l1)
  const l2 = (l1?.children || []).find((n: any) => n.label === cat.l2)
  return (l2?.children || []).map((n: any) => n.label)
})

watch(() => cat.l1, () => { cat.l2 = ''; cat.l3 = '' })
watch(() => cat.l2, () => { cat.l3 = '' })

const createForm = reactive({
  question: '',
  answer: '',
  intent: 'general',
  risk_level: 'low',
  auto_reply: false,
  status: 'draft',
})

function resetCreate() {
  Object.assign(createForm, { question: '', answer: '', intent: 'general', risk_level: 'low', auto_reply: false, status: 'draft' })
}

async function saveCreate() {
  if (!cat.l1 || !createForm.question.trim() || !createForm.answer.trim()) {
    ElMessage.warning('请至少选择一级类目并填写问题/答案')
    return
  }
  try {
    await createQA({
      ...createForm,
      product_id: null,
      category_l1: cat.l1,
      category_l2: cat.l2,
      category_l3: cat.l3,
    })
    ElMessage.success('类目问答已创建')
    resetCreate()
    emit('done')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '创建失败')
  }
}

// manage
const qaList = ref<any[]>([])
const selectedQA = ref<any[]>([])
const manageField = ref<'risk_level' | 'auto_reply' | 'status'>('risk_level')
const manageValue = ref<any>('low')

async function loadCategoryQA() {
  if (!cat.l1) {
    ElMessage.warning('请先选择类目')
    return
  }
  loading.value = true
  try {
    const params: Record<string, any> = { limit: 200, category_l1: cat.l1 }
    if (cat.l2) params.category_l2 = cat.l2
    if (cat.l3) params.category_l3 = cat.l3
    const { data } = await getQAList(params)
    qaList.value = data.items || []
  } catch {
    qaList.value = []
  } finally { loading.value = false }
}

async function applyManage() {
  if (!selectedQA.value.length) {
    ElMessage.warning('请先勾选要修改的问答')
    return
  }
  const payload: Record<string, any> = { [manageField.value]: manageValue.value }
  try {
    await Promise.all(selectedQA.value.map((q) => updateQA(q.id, payload)))
    ElMessage.success(`已更新 ${selectedQA.value.length} 条问答`)
    selectedQA.value = []
    await loadCategoryQA()
    emit('done')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '批量更新失败')
  }
}

async function deleteSelectedQA() {
  if (!selectedQA.value.length) return
  try {
    await ElMessageBox.confirm(`确定删除 ${selectedQA.value.length} 条问答？`, '批量删除', { type: 'warning' })
    await Promise.all(selectedQA.value.map((q) => deleteQA(q.id)))
    ElMessage.success('已删除')
    selectedQA.value = []
    await loadCategoryQA()
    emit('done')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '删除失败')
  }
}

// link existing
const linkKeyword = ref('')
const linkCandidates = ref<any[]>([])

async function searchLinkCandidates() {
  if (!cat.l1) {
    ElMessage.warning('请先选择要关联到的类目')
    return
  }
  loading.value = true
  try {
    const params: Record<string, any> = { limit: 50 }
    if (linkKeyword.value) params.search = linkKeyword.value
    const { data } = await getQAList(params)
    linkCandidates.value = data.items || []
  } catch {
    linkCandidates.value = []
  } finally { loading.value = false }
}

async function linkToCategory(qa: any) {
  try {
    await updateQA(qa.id, {
      product_id: null,
      category_l1: cat.l1,
      category_l2: cat.l2,
      category_l3: cat.l3,
    })
    ElMessage.success('已关联到类目')
    emit('done')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '关联失败')
  }
}

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog :model-value="visible" title="按类目批量管理关联问答" width="960px" destroy-on-close @update:model-value="$emit('update:visible', $event)">
    <div style="margin-bottom:12px">
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:8px">
        <el-select v-model="cat.l1" placeholder="一级类目" clearable size="default" style="width:240px">
          <el-option v-for="opt in l1Options" :key="opt" :label="opt" :value="opt" />
        </el-select>
        <el-select v-model="cat.l2" placeholder="二级类目" clearable size="default" style="width:240px">
          <el-option v-for="opt in l2Options" :key="opt" :label="opt" :value="opt" />
        </el-select>
        <el-select v-model="cat.l3" placeholder="三级类目" clearable size="default" style="width:240px">
          <el-option v-for="opt in l3Options" :key="opt" :label="opt" :value="opt" />
        </el-select>
      </div>
      <div style="font-size:13px;color:#606266">
        已选类目：
        <span style="color:#303133;font-weight:600">
          {{ cat.l1 || '未选择' }}
          <span v-if="cat.l2"> &gt; {{ cat.l2 }}</span>
          <span v-if="cat.l3"> &gt; {{ cat.l3 }}</span>
        </span>
      </div>
    </div>

    <el-radio-group v-model="activeOp" size="small" style="margin-bottom:16px">
      <el-radio-button label="create">新增类目问答</el-radio-button>
      <el-radio-button label="link">关联已有问答到类目</el-radio-button>
      <el-radio-button label="manage">修改 / 删除类目问答</el-radio-button>
    </el-radio-group>

    <!-- create -->
    <div v-if="activeOp === 'create'">
      <el-form label-position="top">
        <el-form-item label="客户问题"><el-input v-model="createForm.question" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="回答"><el-input v-model="createForm.answer" type="textarea" :rows="4" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="意图"><el-input v-model="createForm.intent" /></el-form-item></el-col>
          <el-col :span="8">
            <el-form-item label="风险等级">
              <el-select v-model="createForm.risk_level" style="width:100%">
                <el-option label="低" value="low" /><el-option label="中" value="medium" />
                <el-option label="高" value="high" /><el-option label="极高" value="critical" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="状态">
              <el-select v-model="createForm.status" style="width:100%">
                <el-option label="草稿" value="draft" /><el-option label="待审核" value="pending_review" />
                <el-option label="已发布" value="published" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item><el-checkbox v-model="createForm.auto_reply">允许自动回复</el-checkbox></el-form-item>
      </el-form>
    </div>

    <!-- link -->
    <div v-if="activeOp === 'link'">
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <el-input v-model="linkKeyword" placeholder="搜索已有问答" clearable size="small" @keyup.enter="searchLinkCandidates" />
        <el-button size="small" @click="searchLinkCandidates">搜索</el-button>
      </div>
      <el-table :data="linkCandidates" size="small" stripe v-loading="loading" max-height="360">
        <el-table-column label="问题" prop="question" min-width="200" show-overflow-tooltip />
        <el-table-column label="风险" width="70"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
        <el-table-column label="当前类目" min-width="140"><template #default="{ row }">{{ row.category_l1 || '-' }}{{ row.category_l2 ? ' / ' + row.category_l2 : '' }}</template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }"><el-button size="small" type="primary" @click="linkToCategory(row)">关联到此类目</el-button></template>
        </el-table-column>
      </el-table>
    </div>

    <!-- manage -->
    <div v-if="activeOp === 'manage'">
      <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center">
        <el-button size="small" @click="loadCategoryQA">加载此类目问答</el-button>
        <el-dropdown v-if="selectedQA.length" size="small" split-button type="primary" @click="applyManage">
          批量修改
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="manageField = 'risk_level'; manageValue = 'low'">风险等级</el-dropdown-item>
              <el-dropdown-item @click="manageField = 'auto_reply'; manageValue = true">自动回复</el-dropdown-item>
              <el-dropdown-item @click="manageField = 'status'; manageValue = 'draft'">状态</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-if="selectedQA.length" size="small" type="danger" @click="deleteSelectedQA">批量删除</el-button>
        <span style="font-size:12px;color:#909399">已加载 {{ qaList.length }} 条，选中 {{ selectedQA.length }} 条</span>
      </div>
      <el-table :data="qaList" size="small" stripe v-loading="loading" max-height="360" @selection-change="selectedQA = $event">
        <el-table-column type="selection" width="36" />
        <el-table-column label="问题" prop="question" min-width="200" show-overflow-tooltip />
        <el-table-column label="答案摘要" min-width="140" show-overflow-tooltip><template #default="{ row }">{{ (row.answer||'').slice(0,60) }}...</template></el-table-column>
        <el-table-column label="风险" width="70"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
        <el-table-column label="自动回复" width="80"><template #default="{ row }">{{ row.auto_reply ? '是' : '否' }}</template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }">{{ row.status }}</template></el-table-column>
      </el-table>
      <el-empty v-if="!qaList.length && !loading" description="请点击“加载此类目问答”" />
    </div>

    <template #footer>
      <el-button size="small" @click="close">关闭</el-button>
      <el-button v-if="activeOp === 'create'" size="small" type="primary" @click="saveCreate">保存到类目</el-button>
    </template>
  </el-dialog>
</template>
