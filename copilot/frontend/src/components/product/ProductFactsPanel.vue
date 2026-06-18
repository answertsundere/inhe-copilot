<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Warning } from '@element-plus/icons-vue'
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

function hasValue(value: any): boolean {
  if (value === null || value === undefined) return false
  const str = String(value).trim()
  if (!str) return false
  // 排除无意义占位文案
  if (str === '详见商品详情页') return false
  return true
}

const facts = computed(() => {
  const specs = props.product?.specs || {}
  return factDefs.map((def) => {
    const value = specs[def.field]
    const filled = hasValue(value)
    return {
      ...def,
      customerVisible: filled ? String(value) : '',
      filled,
      updatedBy: props.product?.updated_by || '-',
      updatedAt: props.product?.updated_at || '',
    }
  })
})

const emptyFacts = computed(() => facts.value.filter((f) => !f.filled))
const filledFacts = computed(() => facts.value.filter((f) => f.filled))

async function saveFact(fact: any) {
  if (!props.product) return
  saving.value = true
  try {
    const specs = { ...(props.product.specs || {}), [fact.field]: fact.customerVisible }
    const { data } = await updateProduct(props.product.id, { specs })
    ElMessage.success('商品事实已保存')
    editingFact.value = null
    emit('saved', data)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

function startEdit(fact: any) {
  if (!canEdit.value) {
    ElMessage.warning('当前角色无编辑权限')
    return
  }
  editingFact.value = fact.key
}

function cancelEdit(fact: any) {
  // 取消时恢复原始值
  const specs = props.product?.specs || {}
  fact.customerVisible = hasValue(specs[fact.field]) ? String(specs[fact.field]) : ''
  editingFact.value = null
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

    <div class="facts-summary">
      <div class="summary-item filled">
        <span class="summary-value">{{ filledFacts.length }}</span>
        <span class="summary-label">已填写</span>
      </div>
      <div class="summary-item empty">
        <span class="summary-value">{{ emptyFacts.length }}</span>
        <span class="summary-label">待补充</span>
      </div>
    </div>

    <div class="facts-grid">
      <div
        v-for="fact in facts"
        :key="fact.key"
        class="fact-card"
        :class="[
          fact.filled ? 'is-filled' : 'is-empty',
          { 'is-editing': editingFact === fact.key },
        ]"
      >
        <div class="fact-indicator" />

        <div class="fact-header">
          <div class="fact-meta-row">
            <span class="fact-type">{{ fact.type }}</span>
            <span class="fact-title">{{ fact.label }}</span>
          </div>
          <div class="fact-status">
            <el-tag
              v-if="fact.filled"
              size="small"
              type="success"
              effect="light"
            >
              已填写
            </el-tag>
            <el-tag
              v-else
              size="small"
              type="danger"
              effect="light"
            >
              待补充
            </el-tag>
            <el-tag
              v-if="fact.filled"
              size="small"
              type="success"
              effect="plain"
            >
              可用于回答
            </el-tag>
            <el-tag
              v-else
              size="small"
              type="info"
              effect="plain"
            >
              不可自动回答
            </el-tag>
          </div>
        </div>

        <template v-if="editingFact === fact.key">
          <div class="fact-edit-area">
            <el-input
              v-model="fact.customerVisible"
              type="textarea"
              :rows="4"
              placeholder="填写客户可见回答，保存后 Agent 可引用此事实"
              resize="none"
            />
            <div class="fact-edit-actions">
              <el-button size="small" @click="cancelEdit(fact)">取消</el-button>
              <el-button
                size="small"
                type="primary"
                :loading="saving"
                :disabled="!fact.customerVisible.trim()"
                @click="saveFact(fact)"
              >
                保存
              </el-button>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="fact-content">
            <template v-if="fact.filled">
              <div class="fact-answer">{{ fact.customerVisible }}</div>
            </template>
            <template v-else>
              <div class="fact-empty-body">
                <el-icon :size="28" class="empty-icon"><Warning /></el-icon>
                <div class="empty-title">缺少该事实</div>
                <div class="empty-desc">Agent 不应自动回答此类问题，建议补充后再启用自动回复。</div>
              </div>
            </template>
          </div>

          <div class="fact-footer">
            <div class="fact-updated">
              <span v-if="fact.filled">最近修改：{{ fact.updatedBy }}</span>
              <span v-else>尚未维护</span>
            </div>
            <el-button
              v-if="fact.filled"
              size="small"
              :disabled="!canEdit"
              @click="startEdit(fact)"
            >
              编辑
            </el-button>
            <el-button
              v-else
              size="small"
              type="danger"
              :disabled="!canEdit"
              @click="startEdit(fact)"
            >
              补充资料
            </el-button>
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

.facts-summary {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: var(--kb-radius-lg);
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  box-shadow: var(--kb-shadow-card);
}

.summary-item.filled {
  border-left: 4px solid var(--el-color-success);
}

.summary-item.empty {
  border-left: 4px solid var(--el-color-danger);
}

.summary-value {
  font-size: 20px;
  font-weight: 900;
  color: var(--kb-text-primary);
}

.summary-label {
  font-size: 13px;
  color: var(--kb-text-secondary);
}

.facts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}

.fact-card {
  position: relative;
  border-radius: var(--kb-radius-lg);
  padding: 14px;
  box-shadow: var(--kb-shadow-card);
  transition: all 0.2s ease;
  overflow: hidden;
}

/* 左侧状态指示条 */
.fact-indicator {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
}

.fact-card.is-filled {
  background: #ffffff;
  border: 1px solid var(--kb-border);
}

.fact-card.is-filled .fact-indicator {
  background: var(--el-color-success);
}

.fact-card.is-empty {
  background: linear-gradient(135deg, #fef2f2 0%, #fff1f2 100%);
  border: 1px dashed var(--el-color-danger-light-5);
}

.fact-card.is-empty .fact-indicator {
  background: var(--el-color-danger);
}

.fact-card.is-editing {
  background: #ffffff;
  border: 1px solid var(--el-color-primary);
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.1), var(--kb-shadow-card);
}

.fact-card.is-editing .fact-indicator {
  background: var(--el-color-primary);
}

.fact-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.fact-meta-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fact-type {
  font-size: 11px;
  font-weight: 700;
  color: var(--kb-text-tertiary);
  letter-spacing: 0.5px;
}

.fact-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--kb-text-primary);
}

.fact-status {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.fact-content {
  min-height: 80px;
}

.fact-answer {
  font-size: 14px;
  color: var(--kb-text-primary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 12px;
  background: var(--kb-bg-hover);
  border-radius: var(--kb-radius-md);
}

.fact-empty-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 8px;
  padding: 16px 12px;
  color: var(--kb-text-secondary);
}

.empty-icon {
  color: var(--el-color-danger);
}

.empty-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--kb-text-primary);
}

.empty-desc {
  font-size: 12px;
  color: var(--kb-text-tertiary);
  line-height: 1.5;
}

.fact-edit-area {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.fact-edit-area :deep(.el-textarea__inner) {
  font-size: 14px;
  line-height: 1.6;
}

.fact-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.fact-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--kb-border);
}

.fact-card.is-empty .fact-footer {
  border-top-style: dashed;
  border-top-color: var(--el-color-danger-light-7);
}

.fact-updated {
  font-size: 12px;
  color: var(--kb-text-secondary);
}

@media (max-width: 1366px) {
  .facts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
