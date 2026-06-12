<script setup lang="ts">
import { computed } from 'vue'
import { Grid, List } from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: 'card' | 'table'
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: 'card' | 'table'): void
}>()

const isCard = computed(() => props.modelValue === 'card')
</script>

<template>
  <el-button-group>
    <el-button
      :type="isCard ? 'primary' : 'default'"
      :icon="Grid"
      @click="emit('update:modelValue', 'card')"
    />
    <el-button
      :type="!isCard ? 'primary' : 'default'"
      :icon="List"
      @click="emit('update:modelValue', 'table')"
    />
  </el-button-group>
</template>
