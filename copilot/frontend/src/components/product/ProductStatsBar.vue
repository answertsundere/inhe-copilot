<script setup lang="ts">
import { computed } from 'vue'
import {
  Goods, CircleCheck, Warning, Clock, WarningFilled, ChatDotRound,
} from '@element-plus/icons-vue'

export interface StatItem {
  key: string
  label: string
  value: number
  icon: any
  color: string
  desc?: string
}

const props = defineProps<{
  summary: Record<string, any>
}>()

const emit = defineEmits<{
  click: [key: string]
}>()

const stats = computed<StatItem[]>(() => {
  const s = props.summary || {}
  return [
    { key: 'all', label: '商品总数', value: s.total || 0, icon: Goods, color: '#3b82f6', desc: '全部商品' },
    { key: 'agent_ok', label: 'Agent 可用', value: s.agent_usable || 0, icon: CircleCheck, color: '#22c55e', desc: '可安全供 Agent 调用' },
    { key: 'incomplete', label: '待补全', value: s.incomplete_count || 0, icon: Warning, color: '#f97316', desc: '完整度低于 60%' },
    { key: 'review', label: '待审核', value: s.review_pending || 0, icon: Clock, color: '#6b7280', desc: '等待主管审核' },
    { key: 'high_risk', label: '有风险', value: s.high_risk_product_count || 0, icon: WarningFilled, color: '#ef4444', desc: '关联高风险问答' },
    { key: 'new_feedback', label: '今日新增反馈', value: s.today_feedback_count || 0, icon: ChatDotRound, color: '#8b5cf6', desc: '今日新增反馈' },
    { key: 'avg_completeness', label: '平均完整度', value: s.avg_completeness || 0, icon: CircleCheck, color: '#14b8a6', desc: '商品平均完整度' },
  ]
})

function onClick(key: string) {
  emit('click', key)
}
</script>

<template>
  <div class="stats-bar">
    <div
      v-for="item in stats"
      :key="item.key"
      class="stat-item"
      :style="{ '--stat-color': item.color }"
      :title="item.desc"
      @click="onClick(item.key)"
    >
      <div class="stat-icon-wrap">
        <el-icon :size="20"><component :is="item.icon" /></el-icon>
      </div>
      <div class="stat-body">
        <div class="stat-value">{{ item.value }}</div>
        <div class="stat-label">{{ item.label }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.stats-bar {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px 12px;
  box-shadow: var(--kb-shadow-card);
  cursor: pointer;
  transition: all 0.2s ease;
  border-left: 3px solid var(--stat-color);
}

.stat-item:hover {
  box-shadow: var(--kb-shadow-card-hover);
  transform: translateY(-1px);
}

.stat-icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: var(--kb-radius-md);
  background: color-mix(in srgb, var(--stat-color) 12%, transparent);
  color: var(--stat-color);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--kb-text-primary);
}

.stat-label {
  font-size: 12px;
  color: var(--kb-text-secondary);
  margin-top: 2px;
  white-space: nowrap;
}

@media (max-width: 1366px) {
  .stats-bar {
    grid-template-columns: repeat(4, 1fr);
  }
}
</style>
