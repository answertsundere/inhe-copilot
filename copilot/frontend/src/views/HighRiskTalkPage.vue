<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getQAList, getQARiskControl, createQA, updateQA, deleteQA } from '../api/qa'
import RiskBadge from '../components/common/RiskBadge.vue'

const qaList = ref<any[]>([])
const riskControl = ref<any>(null)
const loading = ref(false)
const isSupervisor = computed(() => {
  const role = localStorage.getItem('kb_user_role') || 'supervisor'
  return role !== 'operator'
})

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const form = reactive({
  question: '',
  answer: '',
  intent: 'general',
  risk_level: 'high',
  auto_reply: false,
})

async function fetchData() {
  loading.value = true
  try {
    const [qaRes, ctrlRes] = await Promise.allSettled([
      getQAList({ risk_level: 'high,critical', limit: 200 }),
      getQARiskControl(),
    ])
    qaList.value = qaRes.status === 'fulfilled' ? (qaRes.value.data.items || []) : []
    riskControl.value = ctrlRes.status === 'fulfilled' ? ctrlRes.value.data : null
  } catch {
    ElMessage.error('加载高风险话术失败')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  Object.assign(form, {
    question: '',
    answer: '',
    intent: 'general',
    risk_level: 'high',
    auto_reply: false,
  })
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  dialogMode.value = 'edit'
  editingId.value = row.id
  Object.assign(form, {
    question: row.question || '',
    answer: row.answer || '',
    intent: row.intent || 'general',
    risk_level: row.risk_level || 'high',
    auto_reply: Boolean(row.auto_reply),
  })
  dialogVisible.value = true
}

async function saveQA() {
  if (!form.question.trim() || !form.answer.trim()) {
    ElMessage.warning('请填写问题和答案')
    return
  }
  try {
    if (dialogMode.value === 'create') {
      await createQA({ ...form, status: 'draft' })
      ElMessage.success('高风险话术已创建')
    } else if (editingId.value) {
      await updateQA(editingId.value, { ...form })
      ElMessage.success('高风险话术已更新')
    }
    dialogVisible.value = false
    await fetchData()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  }
}

async function removeQA(row: any) {
  try {
    await ElMessageBox.confirm('确定删除该高风险话术？', '删除确认', { type: 'warning' })
    await deleteQA(row.id)
    ElMessage.success('已删除')
    await fetchData()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

onMounted(fetchData)
</script>

<template>
  <div v-loading="loading" class="high-risk-page">
    <el-alert
      v-if="riskControl"
      type="warning"
      :closable="false"
      show-icon
      title="风险管控提示"
      :description="`高风险缺 SOP: ${riskControl.high_no_sop?.count ?? 0} 条；高风险允许自动回复: ${riskControl.high_auto_reply?.count ?? 0} 条`"
      style="margin-bottom: 16px"
    />

    <div class="toolbar">
      <el-button v-if="isSupervisor" type="primary" size="small" @click="openCreate">新增高风险话术</el-button>
      <span style="font-size:12px;color:#909399">共 {{ qaList.length }} 条</span>
    </div>

    <el-table :data="qaList" stripe size="small" style="width: 100%">
      <el-table-column label="问题" prop="question" min-width="220" show-overflow-tooltip />
      <el-table-column label="答案摘要" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">{{ (row.answer || '').slice(0, 80) }}{{ (row.answer || '').length > 80 ? '...' : '' }}</template>
      </el-table-column>
      <el-table-column label="意图" prop="intent" width="110" />
      <el-table-column label="风险" width="90"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
      <el-table-column label="自动回复" width="90" align="center"><template #default="{ row }">{{ row.auto_reply ? '是' : '否' }}</template></el-table-column>
      <el-table-column label="状态" prop="status" width="100" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text :disabled="!isSupervisor" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" text type="danger" :disabled="!isSupervisor" @click="removeQA(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!qaList.length && !loading" description="暂无高风险话术" />

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新增高风险话术' : '编辑高风险话术'" width="640px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="客户问题"><el-input v-model="form.question" type="textarea" :rows="2" placeholder="客户可能会怎么问" /></el-form-item>
        <el-form-item label="回答"><el-input v-model="form.answer" type="textarea" :rows="4" placeholder="建议回答内容" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="意图"><el-input v-model="form.intent" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="风险等级">
              <el-select v-model="form.risk_level" style="width:100%">
                <el-option label="高" value="high" />
                <el-option label="极高" value="critical" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-checkbox v-model="form.auto_reply">允许自动回复</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveQA">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.high-risk-page {
  padding: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
</style>
