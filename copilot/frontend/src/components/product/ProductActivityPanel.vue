<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getProductActivityRules } from '../../api/product'

const props = defineProps<{
  product: any
}>()

const loading = ref(false)
const rules = ref<any[]>([])

async function fetchRules() {
  if (!props.product?.id) return
  loading.value = true
  try {
    const { data } = await getProductActivityRules(props.product.id)
    rules.value = data.items || []
  } catch {
    ElMessage.warning('加载活动规则失败')
    rules.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchRules)

function getActivityTypeLabel(type: string) {
  const map: Record<string, string> = {
    coupon: '优惠券',
    review_rebate: '晒图返现/好评',
    gift: '赠品',
    price_protection: '价保',
    other: '其他',
  }
  return map[type] || type || '其他'
}

function formatDate(d: string | null) {
  if (!d) return '未设置'
  try {
    return new Date(d).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return d
  }
}
</script>

<template>
  <div v-loading="loading" class="activity-panel">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="商品活动优惠"
      description="展示当前商品可用的优惠活动。内部价格字段不会展示给客户。"
      style="margin-bottom: 16px"
    />

    <div v-if="rules.length" class="rule-list">
      <div v-for="rule in rules" :key="rule.id" class="rule-card">
        <div class="rule-header">
          <div class="rule-title">{{ rule.title || '未命名活动' }}</div>
          <div class="rule-badges">
            <el-tag size="small" type="primary">{{ getActivityTypeLabel(rule.activity_type) }}</el-tag>
            <el-tag size="small" :type="rule.status === 'active' ? 'success' : 'warning'">
              {{ rule.status === 'active' ? '生效中' : '待生效/待审核' }}
            </el-tag>
            <el-tag v-if="rule.auto_reply_allowed" size="small" type="success">可对客户展示</el-tag>
            <el-tag v-else size="small" type="info">不对客户展示</el-tag>
          </div>
        </div>

        <div class="rule-section">
          <div class="section-label">优惠内容（客户可见）</div>
          <div class="section-content customer-visible">{{ rule.customer_visible_benefit || '-' }}</div>
        </div>

        <div class="rule-section">
          <div class="section-label">参与条件</div>
          <div class="section-content">{{ rule.condition_text || '-' }}</div>
        </div>

        <div class="rule-section">
          <div class="section-label">客户话术</div>
          <div class="section-content reply">{{ rule.customer_reply || '-' }}</div>
        </div>

        <div class="rule-footer">
          <span>生效：{{ formatDate(rule.start_at) }}</span>
          <span>失效：{{ formatDate(rule.end_at) }}</span>
          <span>风险：{{ rule.risk_level || 'low' }}</span>
        </div>
      </div>
    </div>

    <el-empty v-else description="暂无商品活动规则。" />
  </div>
</template>

<style scoped lang="scss">
.activity-panel {
  padding: 4px;
}
.rule-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.rule-card {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 16px;
  box-shadow: var(--kb-shadow-card);
}
.rule-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.rule-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--kb-text-primary);
}
.rule-badges {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.rule-section {
  margin-bottom: 10px;
}
.section-label {
  font-size: 12px;
  color: var(--kb-text-secondary);
  margin-bottom: 4px;
}
.section-content {
  font-size: 13px;
  color: var(--kb-text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.section-content.customer-visible {
  background: var(--kb-success-bg);
  color: var(--kb-success-text);
  padding: 10px 12px;
  border-radius: var(--kb-radius-md);
}
.section-content.reply {
  background: var(--kb-accent-subtle);
  color: var(--kb-text-primary);
  padding: 10px 12px;
  border-radius: var(--kb-radius-md);
}
.rule-footer {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--kb-text-secondary);
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--kb-border);
}
</style>
