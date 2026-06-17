<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getMediaAssets, batchUpdateMediaTags, ASSET_TYPE_LABELS } from '../../api/media'

const props = defineProps<{
  visible: boolean
  categoryTree: any[]
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'done'): void
}>()

const cat = reactive({ l1: '', l2: '', l3: '' })
const selectedTypes = ref<string[]>([])
const mode = ref<'add' | 'remove'>('add')
const tag = ref('')
const loading = ref(false)
const matchedCount = ref(0)

const l1Options = computed(() => props.categoryTree.map((n: any) => n.label))
const l2Options = computed(() => {
  const l1 = props.categoryTree.find((n: any) => n.label === cat.l1)
  return (l1?.children || []).map((n: any) => n.label)
})
const l3Options = computed(() => {
  const l1 = props.categoryTree.find((n: any) => n.label === cat.l1)
  const l2 = (l1?.children || []).find((n: any) => n.label === cat.l2)
  return (l2?.children || []).map((n: any) => n.label)
})

watch(() => cat.l1, () => { cat.l2 = ''; cat.l3 = '' })
watch(() => cat.l2, () => { cat.l3 = '' })

async function preview() {
  if (!cat.l1) {
    ElMessage.warning('请至少选择一级类目')
    return
  }
  loading.value = true
  try {
    const params: Record<string, any> = { limit: 1, category_l1: cat.l1 }
    if (cat.l2) params.category_l2 = cat.l2
    if (cat.l3) params.category_l3 = cat.l3
    if (selectedTypes.value.length) params.asset_type = selectedTypes.value.join(',')
    const { data } = await getMediaAssets(params)
    matchedCount.value = data.total || 0
  } catch {
    matchedCount.value = 0
  } finally { loading.value = false }
}

async function apply() {
  if (!cat.l1) {
    ElMessage.warning('请至少选择一级类目')
    return
  }
  if (!tag.value.trim()) {
    ElMessage.warning('请输入或选择标签')
    return
  }
  loading.value = true
  try {
    // 先拉取所有匹配素材 ID（分页最多 2000）
    const params: Record<string, any> = { limit: 2000, category_l1: cat.l1 }
    if (cat.l2) params.category_l2 = cat.l2
    if (cat.l3) params.category_l3 = cat.l3
    if (selectedTypes.value.length) params.asset_type = selectedTypes.value.join(',')
    const { data } = await getMediaAssets(params)
    const ids = (data.items || []).map((a: any) => a.id)
    if (!ids.length) {
      ElMessage.warning('没有匹配到素材')
      return
    }
    const { data: result } = await batchUpdateMediaTags(
      ids,
      mode.value === 'add' ? [tag.value.trim()] : [],
      mode.value === 'remove' ? [tag.value.trim()] : [],
    )
    ElMessage.success(`已${mode.value === 'add' ? '添加' : '移除'} ${result.updated} 条素材的标签`)
    emit('done')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '批量标签失败')
  } finally { loading.value = false }
}

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog :model-value="visible" title="按类目批量管理素材标签" width="720px" destroy-on-close @update:model-value="$emit('update:visible', $event)">
    <el-form label-position="top">
      <el-form-item label="商品类目">
        <div style="display:flex;gap:8px;margin-bottom:6px">
          <el-select v-model="cat.l1" placeholder="一级类目" clearable size="default" style="flex:1">
            <el-option v-for="opt in l1Options" :key="opt" :label="opt" :value="opt" />
          </el-select>
          <el-select v-model="cat.l2" placeholder="二级类目" clearable size="default" style="flex:1">
            <el-option v-for="opt in l2Options" :key="opt" :label="opt" :value="opt" />
          </el-select>
          <el-select v-model="cat.l3" placeholder="三级类目" clearable size="default" style="flex:1">
            <el-option v-for="opt in l3Options" :key="opt" :label="opt" :value="opt" />
          </el-select>
        </div>
        <div style="font-size:13px;color:#606266">
          已选类目：
          <span style="color:#303133;font-weight:600">
            {{ cat.l1 || '未选择' }}
            <span v-if="cat.l2"> &gt; {{ cat.l2 }}</span>
            <span v-if="cat.l3"> &gt; {{ cat.l3 }}</span>
          </span>
        </div>
      </el-form-item>
      <el-form-item label="素材类型（不选则作用于全部）">
        <el-select v-model="selectedTypes" multiple clearable size="small" style="width:100%">
          <el-option v-for="(label, key) in ASSET_TYPE_LABELS" :key="key" :label="label" :value="key" />
        </el-select>
      </el-form-item>
      <el-form-item label="操作">
        <el-radio-group v-model="mode">
          <el-radio-button label="add">批量添加标签</el-radio-button>
          <el-radio-button label="remove">批量移除标签</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="标签">
        <el-input v-model="tag" placeholder="例如：尺寸" clearable />
      </el-form-item>
    </el-form>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <el-button size="small" @click="preview" :loading="loading">预览匹配数量</el-button>
      <span v-if="matchedCount > 0 || loading === false" style="font-size:13px;color:#606266">匹配素材约 {{ matchedCount }} 条</span>
    </div>
    <template #footer>
      <el-button size="small" @click="close">关闭</el-button>
      <el-button size="small" type="primary" :loading="loading" @click="apply">执行</el-button>
    </template>
  </el-dialog>
</template>
