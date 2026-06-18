<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProducts, getProductSummary, getProductCategoryTree,
  createProduct, batchUpdateProducts,
} from '../api/product'
import ProductStatsBar from '../components/product/ProductStatsBar.vue'
import ProductCardGrid from '../components/product/ProductCardGrid.vue'
import ProductListTable from '../components/product/ProductListTable.vue'
import ProductDetailDrawer from '../components/product/ProductDetailDrawer.vue'
import { useCurrentUser } from '../composables/useCurrentUser'

const { canEdit } = useCurrentUser()

// ─── State ───
const loading = ref(false)
const summary = ref<any>({})
const categoryTree = ref<any[]>([])
const products = ref<any[]>([])
const total = ref(0)
const selectedIds = ref<number[]>([])
const viewMode = ref<'table' | 'card'>('card')

const filters = reactive({
  search: '', category_l1: '', category_l2: '', category_l3: '',
  status: '', agent_usable: '', has_qa: '', missing_field: '', high_risk: '',
  sort_by: 'updated_at', sort_order: 'desc',
  page: 1, page_size: 20,
})

const drawerVisible = ref(false)
const currentProduct = ref<any>(null)
const createDialogVisible = ref(false)
const createForm = reactive<any>({
  product_name: '', i_id: '', brand: 'INHE',
  category_l1: '', category_l2: '', category_l3: '',
  specs: {}, warranty: {}, logistics: {},
})

// ─── Category Tree ───
const treeData = computed(() => categoryTree.value.map((l1: any) => ({
  id: l1.label,
  label: l1.label,
  count: l1.count,
  incomplete: l1.incomplete,
  qa: l1.qa,
  high_risk: l1.high_risk,
  children: (l1.children || []).map((l2: any) => ({
    id: `${l1.label}/${l2.label}`,
    label: l2.label,
    count: l2.count,
    incomplete: l2.incomplete,
    qa: l2.qa,
    high_risk: l2.high_risk,
    children: (l2.children || []).map((l3: any) => ({
      id: `${l1.label}/${l2.label}/${l3.label}`,
      label: l3.label,
      count: l3.count,
      incomplete: l3.incomplete,
      qa: l3.qa,
      high_risk: l3.high_risk,
    })),
  })),
})))

function onTreeNodeClick(data: any) {
  const parts = data.id.split('/')
  filters.category_l1 = parts[0] || ''
  filters.category_l2 = parts[1] || ''
  filters.category_l3 = parts[2] || ''
  filters.page = 1
  fetchProducts()
}

function clearCategory() {
  filters.category_l1 = ''
  filters.category_l2 = ''
  filters.category_l3 = ''
  filters.page = 1
  fetchProducts()
}

// ─── Data Loading ───
async function fetchSummary() {
  try {
    const { data } = await getProductSummary()
    summary.value = data
  } catch {}
}

async function fetchCategoryTree() {
  try {
    const { data } = await getProductCategoryTree()
    categoryTree.value = data
  } catch {}
}

async function fetchProducts() {
  loading.value = true
  try {
    const params: Record<string, any> = {
      limit: filters.page_size,
      offset: (filters.page - 1) * filters.page_size,
    }
    if (filters.search) params.search = filters.search
    if (filters.category_l1) params.category_l1 = filters.category_l1
    if (filters.category_l2) params.category_l2 = filters.category_l2
    if (filters.category_l3) params.category_l3 = filters.category_l3
    if (filters.status) params.status = filters.status
    if (filters.agent_usable) params.agent_usable = filters.agent_usable
    if (filters.has_qa) params.has_qa = filters.has_qa
    if (filters.missing_field) params.missing_field = filters.missing_field
    if (filters.high_risk) params.high_risk = filters.high_risk
    const { data } = await getProducts(params)
    products.value = data.items || []
    total.value = data.total
  } catch {
    ElMessage.error('加载商品列表失败')
  } finally {
    loading.value = false
  }
}

// ─── Filter & View ───
function onStatClick(key: string) {
  filters.status = ''
  filters.agent_usable = ''
  filters.has_qa = ''
  filters.missing_field = ''
  filters.high_risk = ''
  if (key === 'published') filters.status = 'published'
  else if (key === 'incomplete') filters.missing_field = 'incomplete'
  else if (key === 'review') filters.status = 'pending_review'
  else if (key === 'agent_ok') filters.agent_usable = 'yes'
  else if (key === 'high_risk') filters.high_risk = 'yes'
  filters.page = 1
  fetchProducts()
}

function resetFilters() {
  Object.assign(filters, {
    search: '', category_l1: '', category_l2: '', category_l3: '',
    status: '', agent_usable: '', has_qa: '', missing_field: '', high_risk: '',
    sort_by: 'updated_at', sort_order: 'desc', page: 1,
  })
  fetchProducts()
}

// ─── Detail ───
function openDetail(id: number) {
  const p = products.value.find((item) => item.id === id)
  currentProduct.value = p || null
  drawerVisible.value = true
}

function onDetailSaved() {
  fetchProducts()
  fetchSummary()
  if (currentProduct.value?.id) {
    const updated = products.value.find((p) => p.id === currentProduct.value.id)
    if (updated) currentProduct.value = { ...updated }
  }
}

// ─── Create ───
function openCreateDialog() {
  Object.assign(createForm, {
    product_name: '', i_id: '', brand: 'INHE',
    category_l1: '', category_l2: '', category_l3: '',
    specs: {}, warranty: {}, logistics: {},
  })
  createDialogVisible.value = true
}

async function saveCreate() {
  if (!createForm.product_name || !createForm.i_id) {
    ElMessage.warning('请先填写商品名称和商品编码')
    return
  }
  try {
    const { data } = await createProduct({ ...createForm, status: 'draft' })
    ElMessage.success('新增商品成功')
    createDialogVisible.value = false
    await fetchProducts()
    await fetchSummary()
    openDetail(data.id)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '新增商品失败')
  }
}

// ─── Batch ───
async function batchAction(action: string) {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先勾选商品')
    return
  }
  const needsConfirm = ['publish', 'archive'].includes(action)
  if (needsConfirm) {
    try {
      await ElMessageBox.confirm(`确定对 ${selectedIds.value.length} 个商品执行此操作？`, '批量操作确认')
    } catch {
      return
    }
  }
  try {
    await batchUpdateProducts(selectedIds.value, action)
    ElMessage.success('批量操作成功')
    selectedIds.value = []
    await fetchProducts()
    await fetchSummary()
  } catch {
    ElMessage.error('批量操作失败')
  }
}

function onSelectionChange(ids: number[]) {
  selectedIds.value = ids
}

// ─── URL Sync ───
watch(() => filters, () => {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v) params.set(k, String(v))
  })
  history.replaceState(null, '', `${location.pathname}?${params}`)
}, { deep: true })

onMounted(() => {
  const params = new URLSearchParams(location.search)
  params.forEach((v, k) => {
    if (k in filters) {
      (filters as any)[k] = isNaN(Number(v)) ? v : Number(v)
    }
  })
  fetchSummary()
  fetchCategoryTree()
  fetchProducts()
})
</script>

<template>
  <div class="product-page">
    <ProductStatsBar :summary="summary" @click="onStatClick" />

    <el-row :gutter="16" class="main-row">
      <!-- Category Tree -->
      <el-col :span="5">
        <div class="tree-panel">
          <div class="tree-header">
            <span>类目导航</span>
            <el-button v-if="filters.category_l1" link size="small" @click="clearCategory">清除筛选</el-button>
          </div>
          <el-input
            v-model="filters.search"
            placeholder="搜索商品名/SKU"
            clearable
            size="small"
            style="margin-bottom: 8px"
            @clear="fetchProducts"
            @keyup.enter="fetchProducts"
          />
          <el-tree
            :data="treeData"
            :props="{ children: 'children', label: 'label' }"
            node-key="id"
            highlight-current
            default-expand-all
            @node-click="onTreeNodeClick"
          >
            <template #default="{ data }">
              <div class="tree-node">
                <span class="node-label">{{ data.label }}</span>
                <span class="node-badges">
                  <span class="node-count">{{ data.count }}</span>
                  <el-tag v-if="data.incomplete" size="small" type="warning" class="node-tag">{{ data.incomplete }}补</el-tag>
                  <el-tag v-if="data.high_risk" size="small" type="danger" class="node-tag">{{ data.high_risk }}险</el-tag>
                </span>
              </div>
            </template>
          </el-tree>
        </div>
      </el-col>

      <!-- Product List -->
      <el-col :span="19">
        <div class="filter-bar">
          <el-select v-model="filters.status" placeholder="状态" clearable size="small" @change="fetchProducts" style="width: 100px">
            <el-option label="已发布" value="published" />
            <el-option label="草稿" value="draft" />
            <el-option label="待审核" value="pending_review" />
          </el-select>
          <el-select v-model="filters.agent_usable" placeholder="Agent" clearable size="small" @change="fetchProducts" style="width: 110px">
            <el-option label="可用" value="yes" />
            <el-option label="不可用" value="no" />
          </el-select>
          <el-select v-model="filters.missing_field" placeholder="完整度" clearable size="small" @change="fetchProducts" style="width: 120px">
            <el-option label="待补全(<60%)" value="incomplete" />
          </el-select>
          <el-select v-model="filters.sort_by" size="small" @change="fetchProducts" style="width: 130px">
            <el-option label="最近更新" value="updated_at" />
            <el-option label="完整度↑" value="completeness_score" />
          </el-select>
          <el-button size="small" @click="resetFilters">重置</el-button>

          <div style="flex: 1"></div>

          <el-button-group size="small">
            <el-button :type="viewMode === 'table' ? 'primary' : ''" @click="viewMode = 'table'">
              <el-icon><List /></el-icon>
            </el-button>
            <el-button :type="viewMode === 'card' ? 'primary' : ''" @click="viewMode = 'card'">
              <el-icon><Grid /></el-icon>
            </el-button>
          </el-button-group>

          <el-button size="small" type="success" @click="openCreateDialog">新增商品</el-button>

          <el-dropdown trigger="click" :disabled="!selectedIds.length">
            <el-button size="small" type="primary" :disabled="!selectedIds.length">
              批量操作 ({{ selectedIds.length }})
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="batchAction('submit_review')">批量提交审核</el-dropdown-item>
                <el-dropdown-item @click="batchAction('publish')">批量发布</el-dropdown-item>
                <el-dropdown-item @click="batchAction('archive')" divided>批量下线</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <ProductCardGrid
          v-if="viewMode === 'card'"
          :products="products"
          :loading="loading"
          @click="openDetail"
          @fill="openDetail"
          @review="batchAction('submit_review')"
          @retest="openDetail"
        />

        <ProductListTable
          v-else
          :products="products"
          :loading="loading"
          @click="openDetail"
          @selection-change="onSelectionChange"
        />

        <div class="pagination-bar">
          <span class="total-text">共 {{ total }} 件商品</span>
          <el-pagination
            v-model:current-page="filters.page"
            :page-size="filters.page_size"
            :total="total"
            layout="prev, pager, next"
            @current-change="fetchProducts"
          />
        </div>
      </el-col>
    </el-row>

    <ProductDetailDrawer
      v-model="drawerVisible"
      :product="currentProduct"
      @saved="onDetailSaved"
      @review="fetchProducts"
      @publish="fetchProducts"
    />

    <el-dialog v-model="createDialogVisible" title="新增商品" width="720px" destroy-on-close>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="先填写商品名称和商品编码，保存后会进入商品详情继续补全。"
        style="margin-bottom: 16px"
      />
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="商品名称（必填）">
              <el-input v-model="createForm.product_name" placeholder="例如：奶牛篮球架" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="商品编码（必填）">
              <el-input v-model="createForm.i_id" placeholder="例如：YH02K03B01S03" />
            </el-form-item>
          </el-col>
          <el-col :span="8"><el-form-item label="品牌"><el-input v-model="createForm.brand" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="一级类目"><el-input v-model="createForm.category_l1" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="二级类目"><el-input v-model="createForm.category_l2" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCreate">保存并继续维护</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.product-page {
  padding: 16px;
}
.main-row {
  min-height: calc(100vh - 320px);
}
.tree-panel {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 12px;
  box-shadow: var(--kb-shadow-card);
  max-height: calc(100vh - 320px);
  overflow-y: auto;
}
.tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-weight: 600;
  font-size: 14px;
}
.tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  font-size: 13px;
}
.node-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.node-count {
  color: var(--kb-text-tertiary);
  font-size: 11px;
}
.node-tag {
  transform: scale(0.85);
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  padding: 10px 12px;
  border-radius: var(--kb-radius-lg);
  box-shadow: var(--kb-shadow-card);
  flex-wrap: wrap;
}
.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
}
.total-text {
  font-size: 13px;
  color: var(--kb-text-secondary);
}
</style>
