<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: string
}>()

const statusMap: Record<string, { type: '' | 'success' | 'warning' | 'info' | 'danger'; text: string }> = {
  draft: { type: 'info', text: '草稿' },
  pending_review: { type: 'warning', text: '待审核' },
  published: { type: 'success', text: '已发布' },
  rejected: { type: 'danger', text: '已驳回' },
  archived: { type: 'info', text: '已废弃' },
}

const mapped = computed(() => statusMap[props.status])
</script>

<template>
  <el-tag v-if="mapped" :type="mapped.type">{{ mapped.text }}</el-tag>
  <el-tag v-else type="info">
    <slot>{{ status }}</slot>
  </el-tag>
</template>
