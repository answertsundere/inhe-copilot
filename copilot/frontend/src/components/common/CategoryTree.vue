<script setup lang="ts">
import { ref, onMounted } from 'vue'
import apiClient from '../../api/client'

interface TreeNode {
  label: string
  children?: TreeNode[]
}

const emit = defineEmits<{
  (e: 'select', category_l1: string, category_l2: string, category_l3: string): void
}>()

const treeData = ref<TreeNode[]>([])
const loading = ref(false)

function getCategoryPath(node: any): { l1: string; l2: string; l3: string } {
  const segments: string[] = []
  let current = node
  while (current) {
    if (current.data?.label) {
      segments.unshift(current.data.label)
    }
    current = current.parent
  }
  return {
    l1: segments[0] ?? '',
    l2: segments[1] ?? '',
    l3: segments[2] ?? '',
  }
}

function handleNodeClick(data: TreeNode, node: any) {
  const { l1, l2, l3 } = getCategoryPath(node)
  emit('select', l1, l2, l3)
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await apiClient.get<TreeNode[]>('/products/categories')
    treeData.value = res.data ?? []
  } catch (err) {
    console.error('[CategoryTree] Failed to load categories:', err)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading" class="category-tree">
    <el-tree
      :data="treeData"
      :props="{ label: 'label', children: 'children' }"
      node-key="label"
      highlight-current
      default-expand-all
      @node-click="handleNodeClick"
    />
  </div>
</template>

<style scoped>
.category-tree {
  min-height: 100px;
}
</style>
