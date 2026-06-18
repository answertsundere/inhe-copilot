<script setup lang="ts">
import { reactive, watch, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { updateProduct } from '../../api/product'
import { getCompletenessColor, getGapTags } from '../../utils/productStatus'
import { useCurrentUser } from '../../composables/useCurrentUser'

const props = defineProps<{
  product: any
  health: any | null
}>()

const emit = defineEmits<{
  saved: [product: any]
}>()

const { canEdit } = useCurrentUser()

const editMode = ref(false)
const saving = ref(false)
const editForm = reactive<any>({})

const specFields = [
  { key: 'material', label: '材质', span: 12 },
  { key: 'size', label: '尺寸', span: 12 },
  { key: 'load_capacity', label: '承重/容量', span: 12 },
  { key: 'age_range', label: '适用年龄/适用场景', span: 12 },
  { key: 'install_method', label: '安装方式', span: 12 },
  { key: 'accessories', label: '配件清单', span: 12 },
]

const advancedGroups = [
  {
    title: '安装/结构',
    fields: [
      { key: 'detachable', label: '是否可拆卸', placeholder: '例如：可拆卸；抽屉可单独取出' },
      { key: 'drill_required', label: '是否需要打孔', placeholder: '例如：免打孔；需打孔固定' },
      { key: 'installation_time', label: '安装耗时', placeholder: '例如：约20-30分钟' },
      { key: 'installation_difficulty', label: '安装难度', placeholder: '例如：简单，按说明书安装即可' },
      { key: 'rental_friendly', label: '租房/墙面友好', placeholder: '例如：免打孔，不伤墙面' },
    ],
  },
  {
    title: '安全/养护',
    fields: [
      { key: 'pinch_safety', label: '防夹/安全设计', placeholder: '例如：防夹滑轨/圆角设计' },
      { key: 'stability_note', label: '稳定性说明', placeholder: '例如：建议靠墙摆放；需固定防倾倒' },
      { key: 'moisture', label: '防潮/受潮说明', placeholder: '例如：表面可擦拭，避免长期泡水' },
      { key: 'cleaning', label: '清洁保养', placeholder: '例如：湿布擦拭，避免强腐蚀清洁剂' },
      { key: 'odor_note', label: '气味说明', placeholder: '例如：新包装拆开后建议通风' },
      { key: 'certification_report', label: '合格证/质检资料', placeholder: '仅填写已确认的证书、报告或页面公示' },
    ],
  },
]

watch(
  () => props.product,
  (p) => {
    if (!p) return
    Object.assign(editForm, {
      product_name: p.product_name,
      i_id: p.i_id,
      brand: p.brand,
      category_l1: p.category_l1,
      category_l2: p.category_l2,
      category_l3: p.category_l3,
      specs: { ...(p.specs || {}) },
      warranty: { ...(p.warranty || {}) },
      logistics: { ...(p.logistics || {}) },
    })
  },
  { immediate: true },
)

const completenessScore = computed(() => Math.round(props.product?.completeness_score || 0))
const completenessColor = computed(() => getCompletenessColor(completenessScore.value))
const gapTags = computed(() => props.product ? getGapTags(props.product) : [])
const missingFields = computed(() => props.health?.missing_fields || [])

async function saveEdit() {
  if (!props.product) return
  saving.value = true
  try {
    const { data } = await updateProduct(props.product.id, editForm)
    ElMessage.success('保存成功')
    editMode.value = false
    emit('saved', data)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

function cancelEdit() {
  editMode.value = false
  const p = props.product
  if (p) {
    Object.assign(editForm, {
      product_name: p.product_name,
      i_id: p.i_id,
      brand: p.brand,
      category_l1: p.category_l1,
      category_l2: p.category_l2,
      category_l3: p.category_l3,
      specs: { ...(p.specs || {}) },
      warranty: { ...(p.warranty || {}) },
      logistics: { ...(p.logistics || {}) },
    })
  }
}
</script>

<template>
  <div class="basic-panel">
    <div class="panel-header">
      <div class="health-summary">
        <div class="score-circle" :style="{ borderColor: completenessColor, color: completenessColor }">
          <span class="score-num">{{ completenessScore }}</span>
          <span class="score-unit">%</span>
        </div>
        <div class="health-text">
          <div class="health-title">商品卡片完整度</div>
          <div class="health-desc">
            {{ gapTags.length ? `发现 ${gapTags.length} 个缺口` : '关键字段已补齐' }}
          </div>
        </div>
      </div>
      <div class="header-actions">
        <el-button v-if="!editMode" type="primary" :disabled="!canEdit" @click="editMode = true">
          编辑
        </el-button>
        <template v-else>
          <el-button @click="cancelEdit">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
        </template>
      </div>
    </div>

    <div class="gap-tags">
      <el-tag v-for="tag in gapTags" :key="tag.text" size="small" :type="tag.type as any" effect="light">
        {{ tag.text }}
      </el-tag>
      <el-tag v-for="field in missingFields" :key="field" size="small" type="warning" effect="light">
        缺{{ field }}
      </el-tag>
      <el-tag v-if="!gapTags.length && !missingFields.length" size="small" type="success" effect="light">
        资料完整
      </el-tag>
    </div>

    <template v-if="!editMode">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="商品名称">{{ product.product_name }}</el-descriptions-item>
        <el-descriptions-item label="商品编码">{{ product.i_id }}</el-descriptions-item>
        <el-descriptions-item label="品牌">{{ product.brand || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态"><StatusTag :status="product.status" /></el-descriptions-item>
        <el-descriptions-item label="一级类目">{{ product.category_l1 || '-' }}</el-descriptions-item>
        <el-descriptions-item label="二级类目">{{ product.category_l2 || '-' }}</el-descriptions-item>
        <el-descriptions-item label="三级类目">{{ product.category_l3 || '-' }}</el-descriptions-item>
        <el-descriptions-item label="负责人">{{ product.updated_by || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">基础规格</el-divider>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item v-for="field in specFields" :key="field.key" :label="field.label">
          {{ (product.specs || {})[field.key] || '-' }}
        </el-descriptions-item>
      </el-descriptions>

      <template v-for="group in advancedGroups" :key="group.title">
        <el-divider content-position="left">{{ group.title }}</el-divider>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item v-for="field in group.fields" :key="field.key" :label="field.label">
            {{ (product.specs || {})[field.key] || '-' }}
          </el-descriptions-item>
        </el-descriptions>
      </template>

      <el-divider content-position="left">质保/物流</el-divider>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="质保期">{{ (product.warranty || {}).period || '-' }}</el-descriptions-item>
        <el-descriptions-item label="质保范围">{{ (product.warranty || {}).scope || '-' }}</el-descriptions-item>
        <el-descriptions-item label="质保例外">{{ (product.warranty || {}).exclusion || '-' }}</el-descriptions-item>
        <el-descriptions-item label="物流属性">{{ (product.logistics || {}).attribute || '-' }}</el-descriptions-item>
        <el-descriptions-item label="发货说明">{{ (product.logistics || {}).shipping_note || '-' }}</el-descriptions-item>
        <el-descriptions-item label="偏远地区说明">{{ (product.logistics || {}).remote_area_note || '-' }}</el-descriptions-item>
      </el-descriptions>
    </template>

    <template v-else>
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="商品名称"><el-input v-model="editForm.product_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="商品编码"><el-input v-model="editForm.i_id" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="品牌"><el-input v-model="editForm.brand" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="一级类目"><el-input v-model="editForm.category_l1" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="二级类目"><el-input v-model="editForm.category_l2" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="三级类目"><el-input v-model="editForm.category_l3" /></el-form-item></el-col>
        </el-row>

        <el-divider content-position="left">基础规格</el-divider>
        <el-row :gutter="16">
          <el-col v-for="field in specFields" :key="field.key" :span="field.span">
            <el-form-item :label="field.label">
              <el-input v-model="editForm.specs[field.key]" />
            </el-form-item>
          </el-col>
        </el-row>

        <template v-for="group in advancedGroups" :key="group.title">
          <el-divider content-position="left">{{ group.title }}</el-divider>
          <el-row :gutter="16">
            <el-col v-for="field in group.fields" :key="field.key" :span="12">
              <el-form-item :label="field.label">
                <el-input v-model="editForm.specs[field.key]" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" :placeholder="field.placeholder" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-divider content-position="left">质保/物流</el-divider>
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="质保期"><el-input v-model="editForm.warranty.period" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="质保范围"><el-input v-model="editForm.warranty.scope" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="质保例外"><el-input v-model="editForm.warranty.exclusion" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="物流属性"><el-input v-model="editForm.logistics.attribute" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="发货说明"><el-input v-model="editForm.logistics.shipping_note" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="偏远地区说明"><el-input v-model="editForm.logistics.remote_area_note" /></el-form-item></el-col>
        </el-row>
      </el-form>
    </template>
  </div>
</template>

<style scoped lang="scss">
.basic-panel {
  padding: 4px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.health-summary {
  display: flex;
  align-items: center;
  gap: 12px;
}
.score-circle {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 3px solid;
  display: flex;
  align-items: baseline;
  justify-content: center;
  flex-shrink: 0;
}
.score-num {
  font-size: 20px;
  font-weight: 800;
  line-height: 50px;
}
.score-unit {
  font-size: 11px;
  opacity: 0.7;
}
.health-title {
  font-size: 15px;
  font-weight: 600;
}
.health-desc {
  font-size: 13px;
  color: var(--kb-text-secondary);
  margin-top: 2px;
}
.gap-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 16px;
}
</style>
