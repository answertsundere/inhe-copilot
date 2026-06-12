<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  level: string
}>()

type RiskConfig = { color: string; text: string; effect?: 'dark' | 'light' | 'plain' }

const levelMap: Record<string, RiskConfig> = {
  low: { color: '#67c23a', text: '低风险' },
  medium: { color: '#e6a23c', text: '中风险' },
  high: { color: '#f56c6c', text: '高风险', effect: 'dark' },
  critical: { color: '#c62828', text: '极高风险', effect: 'dark' },
}

const config = computed<RiskConfig | undefined>(() => levelMap[props.level])

const tagColor = computed(() => config.value?.color ?? '#909399')
const tagText = computed(() => config.value?.text ?? props.level)
const tagEffect = computed<'dark' | 'light' | 'plain'>(() => config.value?.effect ?? 'light')
</script>

<template>
  <el-tag :color="tagColor" :effect="tagEffect" style="border: none; color: #fff">
    {{ tagText }}
  </el-tag>
</template>
