<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

interface LogisticsRule {
  id: string
  name: string
  type: string
  scope: string
  content: string
  customerReply: string
  status: string
  updatedAt: string
}

const STORAGE_KEY = 'inhe_logistics_rules_v1'

const rules = ref<LogisticsRule[]>([])
const search = ref('')
const typeFilter = ref('')
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref('')

const form = reactive<LogisticsRule>({
  id: '',
  name: '',
  type: '发货时效',
  scope: '全部商品',
  content: '',
  customerReply: '',
  status: 'active',
  updatedAt: '',
})

const ruleTypes = ['发货时效', '偏远地区', '快递合作', '包装要求', '签收异常', '其他']

function loadRules() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    rules.value = raw ? JSON.parse(raw) : []
  } catch {
    rules.value = []
  }
}

function saveRules() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rules.value))
}

const filteredRules = computed(() => {
  return rules.value.filter((r) => {
    if (typeFilter.value && r.type !== typeFilter.value) return false
    if (search.value && !r.name.includes(search.value) && !r.content.includes(search.value)) return false
    return true
  })
})

function resetForm() {
  Object.assign(form, {
    id: '',
    name: '',
    type: '发货时效',
    scope: '全部商品',
    content: '',
    customerReply: '',
    status: 'active',
    updatedAt: '',
  })
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = ''
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: LogisticsRule) {
  dialogMode.value = 'edit'
  editingId.value = row.id
  Object.assign(form, { ...row })
  dialogVisible.value = true
}

function onSave() {
  if (!form.name.trim() || !form.content.trim()) {
    ElMessage.warning('请填写规则名称和内容')
    return
  }
  const now = new Date().toISOString().slice(0, 10)
  if (dialogMode.value === 'create') {
    rules.value.unshift({
      ...form,
      id: Date.now().toString(),
      updatedAt: now,
    })
  } else {
    const idx = rules.value.findIndex((r) => r.id === editingId.value)
    if (idx >= 0) {
      rules.value[idx] = { ...form, updatedAt: now }
    }
  }
  saveRules()
  dialogVisible.value = false
  ElMessage.success('保存成功')
}

async function onDelete(row: LogisticsRule) {
  try {
    await ElMessageBox.confirm('确定删除该物流规则？', '提示', { type: 'warning' })
    rules.value = rules.value.filter((r) => r.id !== row.id)
    saveRules()
    ElMessage.success('已删除')
  } catch {
    // cancel
  }
}

onMounted(loadRules)
</script>

<template>
  <div class="logistics-rules-page">
    <div class="toolbar">
      <el-input v-model="search" placeholder="搜索规则" clearable style="width: 220px" />
      <el-select v-model="typeFilter" placeholder="规则类型" clearable style="width: 160px">
        <el-option v-for="t in ruleTypes" :key="t" :label="t" :value="t" />
      </el-select>
      <el-button type="primary" @click="openCreate">新增物流规则</el-button>
    </div>

    <el-table :data="filteredRules" stripe size="small" style="width: 100%">
      <el-table-column label="规则名称" prop="name" min-width="160" show-overflow-tooltip />
      <el-table-column label="类型" prop="type" width="120" />
      <el-table-column label="适用范围" prop="scope" min-width="140" show-overflow-tooltip />
      <el-table-column label="规则内容" prop="content" min-width="240" show-overflow-tooltip />
      <el-table-column label="客服回复口径" prop="customerReply" min-width="200" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ row.status === 'active' ? '生效中' : '已停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text @click="openEdit(row)">编辑</el-button>
          <el-button size="small" text type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!filteredRules.length" description="暂无物流规则" />

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新增物流规则' : '编辑物流规则'" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="规则名称"><el-input v-model="form.name" placeholder="例如：偏远地区不发货" /></el-form-item>
        <el-form-item label="规则类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option v-for="t in ruleTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用范围"><el-input v-model="form.scope" placeholder="例如：全部商品 / 大件商品" /></el-form-item>
        <el-form-item label="规则内容"><el-input v-model="form.content" type="textarea" :rows="3" placeholder="具体规则说明" /></el-form-item>
        <el-form-item label="客服口径"><el-input v-model="form.customerReply" type="textarea" :rows="3" placeholder="给客服的标准回复" /></el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio label="active">生效中</el-radio>
            <el-radio label="inactive">已停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.logistics-rules-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
}
</style>
