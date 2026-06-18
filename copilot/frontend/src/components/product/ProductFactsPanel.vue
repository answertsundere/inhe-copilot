<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { updateProduct } from '../../api/product'
import { useCurrentUser } from '../../composables/useCurrentUser'

const props = defineProps<{
  product: any
}>()

const emit = defineEmits<{
  saved: [product: any]
}>()

const { canEdit } = useCurrentUser()
const saving = ref(false)
const editingFact = ref<string | null>(null)

interface FactDef {
  key: string
  type: string
  label: string
  field: string
}

const factDefs: FactDef[] = [
  { key: 'size', type: '尺寸', label: '尺寸规格', field: 'size' },
  { key: 'load_capacity', type: '承重', label: '承重/容量', field: 'load_capacity' },
  { key: 'material', type: '材质', label: '材质说明', field: 'material' },
  { key: 'detachable', type: '可拆卸', label: '是否可拆卸', field: 'detachable' },
  { key: 'install_method', type: '安装', label: '安装方式', field: 'install_method' },
  { key: 'accessories', type: '配件', label: '配件清单', field: 'accessories' },
  { key: 'package_list', type: '包装', label: '包装清单', field: 'package_list_note' },
  { key: 'certification_report', type: '证书', label: '合格证/质检', field: 'certification_report' },
  { key: 'odor_note', type: '气味', label: '气味说明', field: 'odor_note' },
  { key: 'cleaning', type: '清洁保养', label: '清洁保养', field: 'cleaning' },
  { key: 'age_range', type: '适用场景', label: '适用年龄/场景', field: 'age_range' },
  { key: 'pinch_safety', type: '安全', label: '安全设计', field: 'pinch_safety' },
]

const facts = computed(() => {
  const specs = props.product?.specs || {}
  return factDefs.map((def) => {
    const value = specs[def.field]
    const hasValue = value && String(value).trim() && String(value) !== '详见商品详情页'
    return {
      ...def,
      customerVisible: hasValue ? String(value) : '',
      internalNote: '',
      riskLevel: 'low',
      allowAutoReply: hasValue,
      auditStatus: props.product?.status === 'published' ? 'approved' : 'draft',
      updatedBy: props.product?.updated_by || '-',
      updatedAt: props.product?.updated_at || '',
      hasValue,
    }
  })
})

const emptyFacts = computed(() => facts.value.filter((f) => !f.hasValue))

async function saveFact(fact: any) {
  if (!props.product) return
  saving.value = true
  try {
    const specs = { ...(props.product.specs || {}), [fact.field]: fact.customerVisible }
    const { data } = await updateProduct(props.product.id, {
      specs,
    })
    ElMessage.success('商品事实已保存')
    editingFact.value = null
    emit('saved', data)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

function getRiskType(level: string) {
  if (level === 'high' || level === 'critical') return 'danger'
  if (level === 'medium') return 'warning'
  return 'success'
}

function getAuditStatusType(status: string) {
  if (status === 'approved') return 'success'
  if (status === 'pending_review') return 'warning'
  if (status === 'rejected') return 'danger'
  return 'info'
}

function getAuditStatusLabel(status: string) {
  if (status === 'approved') return '已审核'
  if (status === 'pending_review') return '待审核'
  if (status === 'rejected') return '已退回'
  return '草稿'
}
</script>

<template>
  <div class="facts-panel">
    <el-alert
      v-if="emptyFacts.length"
      type="warning"
      :closable="false"
      show-icon
      :title="`有 ${emptyFacts.length} 条商品事实待补充`"
      description="商品事实是 Agent 直接回答买家问题的结构化依据，建议优先在“基础资料”里维护对应字段。"
      style="margin-bottom: 16px"
    />

    <div class="facts-grid">
      <div
        v-for="fact in facts"
        :key="fact.key"
        class="fact-card"
        :class="{ 'is-empty': !fact.hasValue }"
      >
        <div class="fact-header">
          <div class="fact-type">{{ fact.type }}</div>
          <div class="fact-status">
            <el-tag size="small" :type="getRiskType(fact.riskLevel)">{{ fact.riskLevel }}</el-tag>
            <el-tag size="small" :type="getAuditStatusType(fact.auditStatus)">
              {{ getAuditStatusLabel(fact.auditStatus) }}
            </el-tag>
          </div>
        </div>

        <div class="fact-title">{{ fact.label }}</div>

        <template v-if="editingFact === fact.key">
          <el-input
            v-model="fact.customerVisible"
            type="textarea"
            :rows="3"
            placeholder="填写客户可见回答"
          />
          <div class="fact-edit-actions">
            <el-button size="small" @click="editingFact = null">取消</el-button>
            <el-button size="small" type="primary" :loading="saving" :disabled="!canEdit" @click="saveFact(fact)">
              保存
            </el-button>
          </div>
        </template>

        <template v-else>
          <div class="fact-answer" :class="{ 'is-empty': !fact.hasValue }">
            {{ fact.customerVisible || '暂无事实，点击编辑补充' }}
          </div>
          <div class="fact-meta">
            <span>自动回答：{{ fact.allowAutoReply ? '允许' : '禁止' }}</span>
            <span>最近修改：{{ fact.updatedBy }}</span>
          </div>
          <div class="fact-actions">
            <el-button size="small" :disabled="!canEdit" @click="editingFact = fact.key">编辑</el-button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.facts-panel {
  padding: 4px;
}
.facts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}
.fact-card {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px;
  box-shadow: var(--kb-shadow-card);
  transition: all 0.2s ease;
}
.fact-card.is-empty {
  border-style: dashed;
  background: var(--kb-bg-hover);
}
.fact-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.fact-type {
  font-size: 12px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
}
.fact-status {
  display: flex;
  gap: 4px;
}
.fact-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--kb-text-primary);
  margin-bottom: 10px;
}
.fact-answer {
  font-size: 13px;
  color: var(--kb-text-primary);
  line-height: 1.6;
  min-height: 40px;
  white-space: pre-wrap;
  word-break: break-word;
}
.fact-answer.is-empty {
  color: var(--kb-text-tertiary);
}
.fact-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--kb-text-secondary);
  margin-top: 10px;
}
.fact-actions {
  margin-top: 10px;
}
.fact-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
</style>
