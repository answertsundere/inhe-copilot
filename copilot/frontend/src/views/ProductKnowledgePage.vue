<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProducts, getProductSummary, getProductCategoryTree,
  getProduct, getProductQA, getProductHealth, getProductVersions,
  createProduct, updateProduct, submitProductReview, publishProduct, batchUpdateProducts,
} from '../api/product'
import StatusTag from '../components/common/StatusTag.vue'
import RiskBadge from '../components/common/RiskBadge.vue'

// ─── State ───
const loading = ref(false)
const summary = ref<any>({})
const categoryTree = ref<any[]>([])
const products = ref<any[]>([])
const total = ref(0)
const selectedIds = ref<number[]>([])
const viewMode = ref<'table' | 'card'>('table')

const filters = reactive({
  search: '', category_l1: '', category_l2: '', category_l3: '',
  status: '', agent_usable: '', has_qa: '', missing_field: '',
  sort_by: 'updated_at', sort_order: 'desc',
  page: 1, page_size: 20,
})

// Drawer
const drawerVisible = ref(false)
const activeTab = ref('basic')
const currentProduct = ref<any>(null)
const productQA = ref<any[]>([])
const productHealth = ref<any>(null)
const productVersions = ref<any[]>([])
const editMode = ref(false)
const editForm = reactive<any>({})
const detailLoading = ref(false)
const qaSearch = ref('')
const qaRiskFilter = ref('')
const createDialogVisible = ref(false)
const createForm = reactive<any>({
  product_name: '',
  i_id: '',
  brand: 'INHE',
  category_l1: '',
  category_l2: '',
  category_l3: '',
  specs: {
    material: '',
    size: '',
    load_capacity: '',
    age_range: '',
    accessories: '',
    install_method: '',
  },
  warranty: { period: '' },
  logistics: { attribute: '' },
})

// ─── Summary Cards ───
const summaryCards = computed(() => {
  const s = summary.value
  return [
    { key: 'all', label: '商品总数', value: s.total || 0, icon: 'Goods', color: '#409eff', desc: '全部商品' },
    { key: 'published', label: '已发布', value: s.published || 0, icon: 'CircleCheck', color: '#67c23a', desc: '可被 Agent 使用' },
    { key: 'incomplete', label: '待补全', value: s.incomplete_count || 0, icon: 'Warning', color: '#e6a23c', desc: '完整度低于60%' },
    { key: 'review', label: '待审核', value: s.review_pending || 0, icon: 'Clock', color: '#909399', desc: '等待主管审核' },
    { key: 'agent_ok', label: 'Agent可用', value: s.agent_usable || 0, icon: 'CircleCheck', color: '#67c23a', desc: '可安全供Agent调用' },
    { key: 'agent_no', label: 'Agent不可用', value: s.not_agent_usable || 0, icon: 'CircleClose', color: '#f56c6c', desc: '需要补全或修复' },
    { key: 'high_risk', label: '高风险商品', value: s.high_risk_product_count || 0, icon: 'Warning', color: '#c62828', desc: '关联高风险问答' },
    { key: 'no_qa', label: '无关联问答', value: s.no_qa_count || 0, icon: 'ChatDotRound', color: '#909399', desc: 'Agent无法回答' },
  ]
})

const healthScore = computed(() => summary.value.health_score || 0)
const healthColor = computed(() => {
  if (healthScore.value >= 80) return '#67c23a'
  if (healthScore.value >= 60) return '#e6a23c'
  return '#f56c6c'
})

function filterByCard(key: string) {
  filters.status = ''; filters.agent_usable = ''; filters.has_qa = ''; filters.missing_field = ''
  if (key === 'published') filters.status = 'published'
  else if (key === 'incomplete') filters.missing_field = 'incomplete'
  else if (key === 'review') filters.status = 'pending_review'
  else if (key === 'agent_ok') filters.agent_usable = 'yes'
  else if (key === 'agent_no') filters.agent_usable = 'no'
  else if (key === 'no_qa') filters.has_qa = 'no'
  filters.page = 1; fetchProducts()
}

// ─── Category Tree ───
const treeData = computed(() => categoryTree.value.map(l1 => ({
  id: l1.label, label: l1.label, count: l1.count, incomplete: l1.incomplete,
  qa: l1.qa, high_risk: l1.high_risk,
  children: (l1.children || []).map((l2: any) => ({
    id: `${l1.label}/${l2.label}`, label: l2.label, count: l2.count,
    incomplete: l2.incomplete, qa: l2.qa, high_risk: l2.high_risk,
    children: (l2.children || []).map((l3: any) => ({
      id: `${l1.label}/${l2.label}/${l3.label}`, label: l3.label, count: l3.count,
      incomplete: l3.incomplete, qa: l3.qa, high_risk: l3.high_risk,
    })),
  })),
})))

function onTreeNodeClick(data: any) {
  const parts = data.id.split('/')
  filters.category_l1 = parts[0] || ''; filters.category_l2 = parts[1] || ''; filters.category_l3 = parts[2] || ''
  filters.page = 1; fetchProducts()
}

function clearCategory() {
  filters.category_l1 = ''; filters.category_l2 = ''; filters.category_l3 = ''
  filters.page = 1; fetchProducts()
}

// ─── Data Loading ───
async function fetchSummary() {
  try { const { data } = await getProductSummary(); summary.value = data } catch {}
}

async function fetchCategoryTree() {
  try { const { data } = await getProductCategoryTree(); categoryTree.value = data } catch {}
}

async function fetchProducts() {
  loading.value = true
  try {
    const params: Record<string, any> = {
      limit: filters.page_size, offset: (filters.page - 1) * filters.page_size,
    }
    if (filters.search) params.search = filters.search
    if (filters.category_l1) params.category_l1 = filters.category_l1
    if (filters.category_l2) params.category_l2 = filters.category_l2
    if (filters.category_l3) params.category_l3 = filters.category_l3
    if (filters.status) params.status = filters.status
    const { data } = await getProducts(params)
    let items = data.items || []
    // Client-side filters
    if (filters.agent_usable === 'yes') items = items.filter((i: any) => i.can_agent_use)
    if (filters.agent_usable === 'no') items = items.filter((i: any) => !i.can_agent_use)
    if (filters.has_qa === 'yes') items = items.filter((i: any) => i.qa_count > 0)
    if (filters.has_qa === 'no') items = items.filter((i: any) => !i.qa_count)
    if (filters.missing_field === 'incomplete') items = items.filter((i: any) => i.completeness_score < 60)
    // Sort
    items.sort((a: any, b: any) => {
      const dir = filters.sort_order === 'desc' ? -1 : 1
      const va = a[filters.sort_by] ?? 0; const vb = b[filters.sort_by] ?? 0
      return va > vb ? dir : va < vb ? -dir : 0
    })
    products.value = items; total.value = data.total
  } catch { ElMessage.error('加载商品列表失败') } finally { loading.value = false }
}

// ─── Product Detail ───
async function openDetail(id: number) {
  detailLoading.value = true; drawerVisible.value = true; activeTab.value = 'basic'; editMode.value = false
  try {
    const { data } = await getProduct(id); currentProduct.value = data
    Object.assign(editForm, {
      product_name: data.product_name, i_id: data.i_id, brand: data.brand,
      category_l1: data.category_l1, category_l2: data.category_l2, category_l3: data.category_l3,
      specs: { ...(data.specs || {}) }, logistics: { ...(data.logistics || {}) },
      warranty: { ...(data.warranty || {}) },
    })
    try { const r = await getProductQA(id); productQA.value = r.data.items || [] } catch { productQA.value = [] }
    try { const r = await getProductHealth(id); productHealth.value = r.data } catch { productHealth.value = null }
    try { const r = await getProductVersions(id); productVersions.value = r.data.items || [] } catch { productVersions.value = [] }
  } catch { ElMessage.error('加载详情失败') } finally { detailLoading.value = false }
}

const filteredQA = computed(() => {
  let list = productQA.value
  if (qaSearch.value) list = list.filter((q: any) => q.question.includes(qaSearch.value) || q.answer.includes(qaSearch.value))
  if (qaRiskFilter.value) list = list.filter((q: any) => q.risk_level === qaRiskFilter.value)
  return list
})

async function saveEdit() {
  try {
    const { data } = await updateProduct(currentProduct.value.id, editForm)
    currentProduct.value = data; editMode.value = false; ElMessage.success('保存成功')
    fetchProducts(); fetchSummary()
  } catch { ElMessage.error('保存失败') }
}

function resetCreateForm() {
  Object.assign(createForm, {
    product_name: '',
    i_id: '',
    brand: 'INHE',
    category_l1: '',
    category_l2: '',
    category_l3: '',
    specs: {
      material: '',
      size: '',
      load_capacity: '',
      age_range: '',
      accessories: '',
      install_method: '',
    },
    warranty: { period: '' },
    logistics: { attribute: '' },
  })
}

function openCreateDialog() {
  resetCreateForm()
  createDialogVisible.value = true
}

async function saveCreate() {
  if (!createForm.product_name || !createForm.i_id) {
    ElMessage.warning('请先填写商品名称和商品编码')
    return
  }
  try {
    const { data } = await createProduct({ ...createForm, status: 'draft' })
    ElMessage.success('新增商品成功，请继续补全资料')
    createDialogVisible.value = false
    await fetchProducts()
    await fetchSummary()
    openDetail(data.id)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '新增商品失败')
  }
}

async function handleSubmitReview() {
  try { await submitProductReview(currentProduct.value.id); ElMessage.success('已提交审核'); openDetail(currentProduct.value.id); fetchProducts() } catch { ElMessage.error('提交失败') }
}

async function handlePublish() {
  try { await ElMessageBox.confirm('确认发布此商品？发布后将可供Agent使用。', '确认发布') } catch { return }
  try { await publishProduct(currentProduct.value.id); ElMessage.success('已发布'); openDetail(currentProduct.value.id); fetchProducts(); fetchSummary() } catch { ElMessage.error('发布失败') }
}

// ─── Batch Operations ───
async function batchAction(action: string) {
  if (!selectedIds.value.length) { ElMessage.warning('请先勾选商品'); return }
  const needsConfirm = ['publish', 'set_agent_use', 'archive'].includes(action)
  if (needsConfirm) {
    try { await ElMessageBox.confirm(`确定对 ${selectedIds.value.length} 个商品执行此操作？`, '批量操作确认') } catch { return }
  }
  try { await batchUpdateProducts(selectedIds.value, action); ElMessage.success('批量操作成功'); selectedIds.value = []; fetchProducts(); fetchSummary() } catch { ElMessage.error('批量操作失败') }
}

function handleSelectionChange(rows: any[]) { selectedIds.value = rows.map((r: any) => r.id) }

// ─── Helpers ───
function completenessColor(score: number) {
  if (score >= 80) return '#67c23a'; if (score >= 60) return '#e6a23c'; return '#f56c6c'
}

function getMissingTags(p: any) {
  const tags: { text: string; type: string }[] = []
  const sp = p.specs || {}
  if (!sp.material || sp.material === '详见商品详情页') tags.push({ text: '缺材质', type: 'warning' })
  if (!sp.size || sp.size === '详见商品详情页') tags.push({ text: '缺尺寸', type: 'warning' })
  if (!sp.load_capacity) tags.push({ text: '缺承重', type: 'warning' })
  if (!sp.age_range) tags.push({ text: '缺年龄', type: 'warning' })
  if (!(p.warranty || {}).period) tags.push({ text: '缺质保', type: 'warning' })
  if (!(p.logistics || {}).attribute) tags.push({ text: '缺物流', type: 'warning' })
  if (!p.qa_count) tags.push({ text: '无问答', type: 'info' })
  if (p.high_risk_qa_count) tags.push({ text: `${p.high_risk_qa_count}高风险`, type: 'danger' })
  if (!p.can_agent_use) tags.push({ text: 'Agent不可用', type: 'danger' })
  return tags
}

function agentBlockReason(p: any) {
  const reasons: string[] = []
  if (p.status !== 'published') reasons.push('未发布')
  if (p.completeness_score < 60) reasons.push(`完整度${p.completeness_score}%`)
  if (p.high_risk_qa_count) reasons.push(`${p.high_risk_qa_count}条高风险问答`)
  if (!p.qa_count) reasons.push('无关联问答')
  return reasons.join('、') || '可安全使用'
}

function resetFilters() {
  Object.assign(filters, { search: '', category_l1: '', category_l2: '', category_l3: '', status: '', agent_usable: '', has_qa: '', missing_field: '', sort_by: 'updated_at', sort_order: 'desc', page: 1 })
  fetchProducts()
}

// Sync URL params
watch(() => filters, () => {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, String(v)) })
  history.replaceState(null, '', `${location.pathname}?${params}`)
}, { deep: true })

onMounted(() => {
  // Restore from URL
  const params = new URLSearchParams(location.search)
  params.forEach((v, k) => { if (k in filters) (filters as any)[k] = isNaN(Number(v)) ? v : Number(v) })
  fetchSummary(); fetchCategoryTree(); fetchProducts()
})
</script>

<template>
  <div class="product-page">
    <!-- RAG Tip -->
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
      <template #title>
        此页面展示商品主数据（kb_product）；由商品 RAG 导入脚本生成的草稿，请前往
        <router-link to="/rag" style="color:#409eff;font-weight:600">RAG 知识条目</router-link>
        查看和审核。
      </template>
    </el-alert>

    <!-- Health Score Banner -->
    <div class="health-banner">
      <div class="health-score-circle" :style="{ borderColor: healthColor, color: healthColor }">
        <span class="score-num">{{ healthScore }}</span>
        <span class="score-label">/ 100</span>
      </div>
      <div class="health-info">
        <div class="health-title">商品知识库健康度</div>
        <div class="health-desc">平均完整度 {{ summary.avg_completeness }}% · 已发布 {{ summary.published }} / {{ summary.total }} · Agent可用 {{ summary.agent_usable }}</div>
      </div>
    </div>

    <!-- Summary Cards -->
    <el-row :gutter="10" class="summary-row">
      <el-col v-for="card in summaryCards" :key="card.key" :span="3">
        <div class="summary-card" :style="{ borderTopColor: card.color }" @click="filterByCard(card.key)" :title="card.desc">
          <div class="card-value" :style="{ color: card.color }">{{ card.value }}</div>
          <div class="card-label">{{ card.label }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- Main Layout -->
    <el-row :gutter="16" class="main-row">
      <!-- Left: Category Tree -->
      <el-col :span="5">
        <div class="tree-panel">
          <div class="tree-header">
            <span>类目导航</span>
            <el-button v-if="filters.category_l1" link size="small" @click="clearCategory">清除筛选</el-button>
          </div>
          <el-input v-model="filters.search" placeholder="搜索商品名/SKU" clearable size="small" style="margin-bottom:8px" @clear="fetchProducts" @keyup.enter="fetchProducts" />
          <el-tree :data="treeData" :props="{ children: 'children', label: 'label' }" node-key="id" highlight-current default-expand-all @node-click="onTreeNodeClick">
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

      <!-- Right: Product List -->
      <el-col :span="19">
        <!-- Filter Bar -->
        <div class="filter-bar">
          <el-select v-model="filters.status" placeholder="状态" clearable size="small" @change="fetchProducts" style="width:90px">
            <el-option label="已发布" value="published" /><el-option label="草稿" value="draft" /><el-option label="待审核" value="pending_review" />
          </el-select>
          <el-select v-model="filters.agent_usable" placeholder="Agent" clearable size="small" @change="fetchProducts" style="width:100px">
            <el-option label="可用" value="yes" /><el-option label="不可用" value="no" />
          </el-select>
          <el-select v-model="filters.has_qa" placeholder="关联问答" clearable size="small" @change="fetchProducts" style="width:100px">
            <el-option label="有关联" value="yes" /><el-option label="无关联" value="no" />
          </el-select>
          <el-select v-model="filters.missing_field" placeholder="完整度" clearable size="small" @change="fetchProducts" style="width:100px">
            <el-option label="待补全(<60%)" value="incomplete" />
          </el-select>
          <el-select v-model="filters.sort_by" size="small" @change="fetchProducts" style="width:120px">
            <el-option label="最近更新" value="updated_at" /><el-option label="完整度↑" value="completeness_score" /><el-option label="问答数↓" value="qa_count" />
          </el-select>
          <el-button size="small" @click="resetFilters">重置</el-button>
          <div style="flex:1"></div>
          <el-button-group size="small">
            <el-button :type="viewMode==='table'?'primary':''" @click="viewMode='table'"><el-icon><List /></el-icon></el-button>
            <el-button :type="viewMode==='card'?'primary':''" @click="viewMode='card'"><el-icon><Grid /></el-icon></el-button>
          </el-button-group>
          <el-button size="small" type="success" @click="openCreateDialog">新增商品</el-button>
          <el-dropdown trigger="click" :disabled="!selectedIds.length">
            <el-button size="small" type="primary" :disabled="!selectedIds.length">批量操作 ({{ selectedIds.length }})</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="batchAction('submit_review')">批量提交审核</el-dropdown-item>
                <el-dropdown-item @click="batchAction('publish')">批量发布</el-dropdown-item>
                <el-dropdown-item @click="batchAction('archive')" divided>批量下线</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <!-- Table View -->
        <el-table v-if="viewMode==='table'" v-loading="loading" :data="products" stripe size="small" @selection-change="handleSelectionChange" style="width:100%">
          <el-table-column type="selection" width="36" />
          <el-table-column label="商品" min-width="200">
            <template #default="{ row }">
              <a class="product-link" @click="openDetail(row.id)">{{ row.product_name }}</a>
              <div class="sku-line">{{ row.i_id }}</div>
            </template>
          </el-table-column>
          <el-table-column label="类目" width="150">
            <template #default="{ row }">
              <div class="cat-text">{{ row.category_l1 }}</div>
              <div class="cat-sub">{{ row.category_l2 }}{{ row.category_l3 ? ' / ' + row.category_l3 : '' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="完整度" width="120" sortable>
            <template #default="{ row }">
              <el-progress :percentage="row.completeness_score" :stroke-width="12" :color="completenessColor(row.completeness_score)" :format="(p:number) => p+'%'" />
            </template>
          </el-table-column>
          <el-table-column label="问答" width="70" align="center">
            <template #default="{ row }">
              <span :class="row.qa_count ? '' : 'text-muted'">{{ row.qa_count || 0 }}</span>
              <el-tag v-if="row.high_risk_qa_count" type="danger" size="small" style="margin-left:2px">{{ row.high_risk_qa_count }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Agent" width="100" align="center">
            <template #default="{ row }">
              <el-tooltip :content="agentBlockReason(row)" placement="top">
                <el-tag :type="row.can_agent_use ? 'success' : 'danger'" size="small">{{ row.can_agent_use ? '可用' : '不可用' }}</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="健康标签" min-width="180">
            <template #default="{ row }">
              <el-tag v-for="tag in getMissingTags(row).slice(0,3)" :key="tag.text" size="small" :type="tag.type as any" style="margin:1px 2px">{{ tag.text }}</el-tag>
              <el-tag v-if="getMissingTags(row).length > 3" size="small" type="info">+{{ getMissingTags(row).length - 3 }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openDetail(row.id)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- Card View -->
        <el-row v-if="viewMode==='card'" :gutter="12" v-loading="loading">
          <el-col v-for="p in products" :key="p.id" :span="8" style="margin-bottom:12px">
            <el-card shadow="hover" class="product-card" @click="openDetail(p.id)">
              <div class="pc-header">
                <a class="product-link">{{ p.product_name }}</a>
                <el-tooltip :content="agentBlockReason(p)" placement="top">
                  <el-tag :type="p.can_agent_use ? 'success' : 'danger'" size="small">{{ p.can_agent_use ? 'Agent可用' : '不可用' }}</el-tag>
                </el-tooltip>
              </div>
              <div class="pc-sku">{{ p.i_id }}</div>
              <div class="pc-cat">{{ p.category_l1 }} / {{ p.category_l2 }}</div>
              <el-progress :percentage="p.completeness_score" :stroke-width="10" :color="completenessColor(p.completeness_score)" :format="(v:number) => v+'%'" style="margin:8px 0" />
              <div class="pc-bottom">
                <span>问答 {{ p.qa_count || 0 }}</span>
                <span v-if="p.high_risk_qa_count" style="color:#f56c6c">高风险 {{ p.high_risk_qa_count }}</span>
                <StatusTag :status="p.status" />
              </div>
              <div class="pc-tags">
                <el-tag v-for="tag in getMissingTags(p).slice(0,3)" :key="tag.text" size="small" :type="tag.type as any" style="margin:1px">{{ tag.text }}</el-tag>
              </div>
            </el-card>
          </el-col>
          <el-col v-if="!loading && !products.length" :span="24"><el-empty description="暂无商品数据" /></el-col>
        </el-row>

        <!-- Pagination -->
        <div class="pagination-bar">
          <span class="total-text">共 {{ total }} 件商品</span>
          <el-pagination v-model:current-page="filters.page" :page-size="filters.page_size" :total="total" layout="prev, pager, next" @current-change="fetchProducts" />
        </div>
      </el-col>
    </el-row>

    <!-- Detail Drawer -->
    <el-drawer v-model="drawerVisible" :title="currentProduct?.product_name || '商品详情'" size="70%" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="currentProduct">
          <!-- Agent Status Banner -->
          <el-alert v-if="productHealth" :title="productHealth.can_agent_use ? '此商品可用于智能客服 Agent' : '此商品暂不可用于 Agent'" :type="productHealth.can_agent_use ? 'success' : 'warning'" :description="productHealth.agent_block_reason || agentBlockReason(currentProduct)" show-icon :closable="false" style="margin-bottom:16px" />

          <el-tabs v-model="activeTab">
            <!-- Tab 1: Basic Info -->
            <el-tab-pane label="基础资料" name="basic">
              <template v-if="!editMode">
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="商品名称">{{ currentProduct.product_name }}</el-descriptions-item>
                  <el-descriptions-item label="商品编码">{{ currentProduct.i_id }}</el-descriptions-item>
                  <el-descriptions-item label="品牌">{{ currentProduct.brand }}</el-descriptions-item>
                  <el-descriptions-item label="状态"><StatusTag :status="currentProduct.status" /></el-descriptions-item>
                  <el-descriptions-item label="一级类目">{{ currentProduct.category_l1 }}</el-descriptions-item>
                  <el-descriptions-item label="二级类目">{{ currentProduct.category_l2 }}</el-descriptions-item>
                  <el-descriptions-item label="三级类目">{{ currentProduct.category_l3 }}</el-descriptions-item>
                  <el-descriptions-item label="材质">{{ (currentProduct.specs||{}).material || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="尺寸">{{ (currentProduct.specs||{}).size || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="承重/容量">{{ (currentProduct.specs||{}).load_capacity || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="适用年龄">{{ (currentProduct.specs||{}).age_range || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="配件清单">{{ (currentProduct.specs||{}).accessories || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="安装方式">{{ (currentProduct.specs||{}).install_method || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="质保期">{{ (currentProduct.warranty||{}).period || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="物流属性" :span="2">{{ (currentProduct.logistics||{}).attribute || '-' }}</el-descriptions-item>
                </el-descriptions>
                <div style="margin-top:16px;text-align:right">
                  <el-button type="primary" @click="editMode=true">编辑</el-button>
                  <el-button v-if="currentProduct.status==='draft'" type="warning" @click="handleSubmitReview">提交审核</el-button>
                  <el-button v-if="currentProduct.status==='pending_review'" type="success" @click="handlePublish">发布</el-button>
                </div>
              </template>
              <template v-else>
                <el-form label-position="top">
                  <el-row :gutter="16">
                    <el-col :span="12"><el-form-item label="商品名称"><el-input v-model="editForm.product_name" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="商品编码"><el-input v-model="editForm.i_id" /></el-form-item></el-col>
                    <el-col :span="8"><el-form-item label="一级类目"><el-input v-model="editForm.category_l1" /></el-form-item></el-col>
                    <el-col :span="8"><el-form-item label="二级类目"><el-input v-model="editForm.category_l2" /></el-form-item></el-col>
                    <el-col :span="8"><el-form-item label="三级类目"><el-input v-model="editForm.category_l3" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="材质"><el-input v-model="editForm.specs.material" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="尺寸"><el-input v-model="editForm.specs.size" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="承重/容量"><el-input v-model="editForm.specs.load_capacity" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="适用年龄"><el-input v-model="editForm.specs.age_range" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="配件清单"><el-input v-model="editForm.specs.accessories" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="安装方式"><el-input v-model="editForm.specs.install_method" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="质保期"><el-input v-model="editForm.warranty.period" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="物流属性"><el-input v-model="editForm.logistics.attribute" /></el-form-item></el-col>
                  </el-row>
                </el-form>
                <div style="text-align:right"><el-button @click="editMode=false">取消</el-button><el-button type="primary" @click="saveEdit">保存</el-button></div>
              </template>
            </el-tab-pane>

            <!-- Tab 2: Related QA -->
            <el-tab-pane label="关联问答" name="qa">
              <div style="display:flex;gap:8px;margin-bottom:12px">
                <el-input v-model="qaSearch" placeholder="搜索问答" clearable size="small" style="width:200px" />
                <el-select v-model="qaRiskFilter" placeholder="风险等级" clearable size="small" style="width:100px">
                  <el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="极高" value="critical" />
                </el-select>
                <div style="flex:1"></div>
                <span style="font-size:12px;color:#909399">共 {{ filteredQA.length }} 条</span>
              </div>
              <el-table :data="filteredQA" size="small" stripe>
                <el-table-column label="客户问题" prop="question" min-width="180" show-overflow-tooltip />
                <el-table-column label="答案摘要" min-width="180"><template #default="{ row }">{{ (row.answer||'').slice(0,80) }}{{ (row.answer||'').length > 80 ? '...' : '' }}</template></el-table-column>
                <el-table-column label="意图" prop="intent" width="100" />
                <el-table-column label="风险" width="70"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
                <el-table-column label="自动回复" width="70" align="center"><template #default="{ row }"><el-icon v-if="row.auto_reply" color="#67c23a"><CircleCheck /></el-icon><el-icon v-else color="#909399"><CircleClose /></el-icon></template></el-table-column>
                <el-table-column label="状态" width="70"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
              </el-table>
              <el-empty v-if="!filteredQA.length" description="暂无关联问答" />
            </el-tab-pane>

            <!-- Tab 3: Health -->
            <el-tab-pane label="数据健康" name="health">
              <template v-if="productHealth">
                <el-row :gutter="16" style="margin-bottom:16px">
                  <el-col :span="6"><div class="stat-mini"><div class="stat-mini-val">{{ productHealth.completeness_score }}%</div><div class="stat-mini-lbl">完整度</div></div></el-col>
                  <el-col :span="6"><div class="stat-mini"><div class="stat-mini-val">{{ productHealth.qa_count }}</div><div class="stat-mini-lbl">关联问答</div></div></el-col>
                  <el-col :span="6"><div class="stat-mini"><div class="stat-mini-val" :style="{color:productHealth.total_issues?'#f56c6c':'#67c23a'}">{{ productHealth.total_issues }}</div><div class="stat-mini-lbl">健康问题</div></div></el-col>
                  <el-col :span="6"><div class="stat-mini"><div class="stat-mini-val"><el-tag :type="productHealth.can_agent_use?'success':'danger'" size="small">{{ productHealth.can_agent_use?'可用':'不可用' }}</el-tag></div><div class="stat-mini-lbl">Agent状态</div></div></el-col>
                </el-row>
                <el-table :data="productHealth.issues" size="small" stripe>
                  <el-table-column label="严重程度" width="100">
                    <template #default="{ row }"><el-tag :type="row.severity==='critical'?'danger':row.severity==='warning'?'warning':'info'" size="small">{{ row.severity==='critical'?'严重':row.severity==='warning'?'警告':'提示' }}</el-tag></template>
                  </el-table-column>
                  <el-table-column label="问题描述" prop="message" min-width="200" />
                </el-table>
              </template>
              <el-empty v-else description="健康数据加载中..." />
            </el-tab-pane>

            <!-- Tab 4: Versions -->
            <el-tab-pane label="版本记录" name="versions">
              <el-timeline>
                <el-timeline-item v-for="v in productVersions" :key="v.id" :timestamp="v.created_at?.replace('T',' ').slice(0,19)" placement="top">
                  <el-card shadow="never">
                    <div><strong>{{ v.action }}</strong> by {{ v.performed_by }}</div>
                    <div v-if="v.change_reason" style="color:#909399;font-size:12px;margin-top:4px">{{ v.change_reason }}</div>
                    <div v-if="v.changed_fields?.length" style="margin-top:4px"><el-tag v-for="f in v.changed_fields" :key="f" size="small" style="margin:2px">{{ f }}</el-tag></div>
                  </el-card>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-if="!productVersions.length" description="暂无版本记录" />
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>

    <el-dialog v-model="createDialogVisible" title="新增商品" width="72%" destroy-on-close>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="先填写商品名称和商品编码，保存后会进入商品详情继续补全。新增商品默认是草稿，需要提交审核后再发布。"
        style="margin-bottom:16px"
      />
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="商品名称（必填）"><el-input v-model="createForm.product_name" placeholder="例如：奶牛篮球架" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="商品编码（必填）"><el-input v-model="createForm.i_id" placeholder="例如：YH02K03B01S03" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="品牌"><el-input v-model="createForm.brand" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="一级类目"><el-input v-model="createForm.category_l1" placeholder="例如：运动户外" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="二级类目"><el-input v-model="createForm.category_l2" placeholder="例如：篮球架" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="三级类目"><el-input v-model="createForm.category_l3" placeholder="例如：儿童篮球架" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="材质"><el-input v-model="createForm.specs.material" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="尺寸"><el-input v-model="createForm.specs.size" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="承重/容量"><el-input v-model="createForm.specs.load_capacity" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="适用年龄"><el-input v-model="createForm.specs.age_range" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="配件清单"><el-input v-model="createForm.specs.accessories" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="安装方式"><el-input v-model="createForm.specs.install_method" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="质保期"><el-input v-model="createForm.warranty.period" /></el-form-item></el-col>
          <el-col :span="16"><el-form-item label="物流属性"><el-input v-model="createForm.logistics.attribute" placeholder="例如：大件/普通件/易碎件/需分包" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible=false">取消</el-button>
        <el-button type="primary" @click="saveCreate">保存并继续维护</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.product-page { padding: 16px; }
.health-banner { display: flex; align-items: center; gap: 20px; background: #fff; border-radius: 12px; padding: 20px 24px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.health-score-circle { width: 72px; height: 72px; border-radius: 50%; border: 4px solid; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; }
.score-num { font-size: 24px; font-weight: 800; line-height: 1; }
.score-label { font-size: 11px; opacity: .6; }
.health-title { font-size: 16px; font-weight: 600; color: #303133; }
.health-desc { font-size: 13px; color: #909399; margin-top: 4px; }
.summary-row { margin-bottom: 16px; }
.summary-card { background: #fff; border-radius: 8px; padding: 14px; cursor: pointer; border-top: 3px solid; box-shadow: 0 1px 4px rgba(0,0,0,.06); transition: all .2s; }
.summary-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.1); transform: translateY(-1px); }
.card-value { font-size: 22px; font-weight: 700; }
.card-label { font-size: 12px; color: #909399; margin-top: 2px; }
.main-row { min-height: calc(100vh - 340px); }
.tree-panel { background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); max-height: calc(100vh - 340px); overflow-y: auto; }
.tree-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 600; font-size: 14px; }
.tree-node { display: flex; align-items: center; justify-content: space-between; width: 100%; font-size: 13px; }
.node-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-badges { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.node-count { color: #909399; font-size: 11px; }
.node-tag { transform: scale(0.8); }
.filter-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; background: #fff; padding: 10px 12px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.06); flex-wrap: wrap; }
.product-link { color: #409eff; cursor: pointer; font-weight: 500; font-size: 13px; }
.product-link:hover { text-decoration: underline; }
.sku-line { font-size: 11px; color: #909399; }
.cat-text { font-size: 13px; }
.cat-sub { font-size: 11px; color: #909399; }
.text-muted { color: #c0c4cc; }
.product-card { cursor: pointer; transition: all .2s; }
.product-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.12); }
.pc-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
.pc-sku { font-size: 11px; color: #909399; }
.pc-cat { font-size: 12px; color: #606266; margin: 4px 0; }
.pc-bottom { display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #909399; }
.pc-tags { margin-top: 8px; }
.pagination-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; }
.total-text { font-size: 13px; color: #909399; }
.stat-mini { background: #fff; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.stat-mini-val { font-size: 20px; font-weight: 700; color: #303133; }
.stat-mini-lbl { font-size: 11px; color: #909399; margin-top: 2px; }
</style>
