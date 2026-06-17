<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getQAList, getQASummary, getQA, updateQA, getQAHealth, getQAProduct,
  getQAVersions, getQAVariants, addVariant, removeVariant,
  submitQAReview, publishQA, getQAIntents, batchUpdateQA,
  getQAProductTree, getQAScenarioTree, getQARiskTree, getQASOP,
  getQARiskControl,
} from '../api/qa'
import StatusTag from '../components/common/StatusTag.vue'
import RiskBadge from '../components/common/RiskBadge.vue'

// ─── State ───
const loading = ref(false)
const summary = ref<any>({})
const qaList = ref<any[]>([])
const total = ref(0)
const selectedIds = ref<number[]>([])
const viewMode = ref<'table' | 'card'>('table')
const intentOptions = ref<string[]>([])

const navMode = ref<'product' | 'scenario' | 'risk' | 'control'>('scenario')
const navTree = ref<any[]>([])
const riskControl = ref<any>(null)
const riskControlLabels: Record<string, string> = {
  high_no_sop: '高风险缺SOP',
  high_auto_reply: '高风险允许自动回复',
}
const navLoading = ref(false)
const expandedNav = ref<string[]>([])

const filters = reactive({
  search: '', intent: '', risk_level: '', status: '', source_type: '',
  auto_reply: '', scenario_category: '', issue_type: '',
  category_l1: '', category_l2: '', category_l3: '', sop_status: '', content_contains: '',
  page: 1, page_size: 20,
})

// Drawer
const drawerVisible = ref(false)
const activeTab = ref('basic')
const currentQA = ref<any>(null)
const qaHealth = ref<any>(null)
const qaProduct = ref<any>(null)
const qaSOP = ref<any>(null)
const qaVariants = ref<any[]>([])
const qaVersions = ref<any[]>([])
const editMode = ref(false)
const editForm = reactive<any>({})
const detailLoading = ref(false)
const newVariant = ref('')

// ─── Summary Cards ───
const summaryCards = computed(() => {
  const s = summary.value
  return [
    { key: 'all', label: '问答总数', value: s.total || 0, color: '#409eff' },
    { key: 'published', label: '已发布', value: s.published || 0, color: '#67c23a' },
    { key: 'pending', label: '待审核', value: s.pending_review || 0, color: '#e6a23c' },
    { key: 'auto_yes', label: '可自动回复', value: s.auto_reply_yes || 0, color: '#67c23a' },
    { key: 'high_risk', label: '中高风险', value: (s.risk_medium || 0) + (s.risk_high || 0) + (s.risk_critical || 0), color: '#f56c6c' },
    { key: 'agent_ok', label: 'Agent可用', value: s.agent_usable || 0, color: '#67c23a' },
    { key: 'agent_no', label: 'Agent不可用', value: s.not_agent_usable || 0, color: '#f56c6c' },
    { key: 'no_product', label: '无关联商品', value: s.no_product || 0, color: '#e6a23c' },
  ]
})

function filterByCard(key: string) {
  filters.status = ''; filters.risk_level = ''; filters.auto_reply = ''
  if (key === 'published') filters.status = 'published'
  else if (key === 'pending') filters.status = 'pending_review'
  else if (key === 'auto_yes') filters.auto_reply = 'true'
  else if (key === 'auto_no') filters.auto_reply = 'false'
  else if (key === 'high_risk') filters.risk_level = 'medium,high,critical'
  filters.page = 1; fetchQAList()
}

// ─── Navigation Trees ───
async function fetchNavTree() {
  navLoading.value = true
  try {
    if (navMode.value === 'control') {
      const { data } = await getQARiskControl()
      riskControl.value = data
      navTree.value = []
    } else {
      riskControl.value = null
      let res
      if (navMode.value === 'product') res = await getQAProductTree()
      else if (navMode.value === 'scenario') res = await getQAScenarioTree()
      else res = await getQARiskTree()
      navTree.value = res.data
      if (navMode.value === 'risk') {
        expandedNav.value = ['低风险', '中风险', '高风险', '极高风险']
      }
    }
  } catch { navTree.value = [] } finally { navLoading.value = false }
}

function onNavClick(data: any, mode: string) {
  // Reset filters
  filters.category_l1 = ''; filters.category_l2 = ''; filters.category_l3 = ''
  filters.scenario_category = ''; filters.issue_type = ''
  filters.risk_level = ''; filters.sop_status = ''; filters.auto_reply = ''

  if (mode === 'product') {
    // data.label is category name, check level by parent context
    if (data.children?.length) {
      // Has children = l1 or l2
      const hasGrandchildren = data.children.some((c: any) => c.children?.length)
      if (hasGrandchildren) {
        filters.category_l1 = data.label
      } else {
        filters.category_l2 = data.label
      }
    } else {
      filters.category_l3 = data.label
    }
  } else if (mode === 'scenario') {
    if (data.children?.length) {
      // Parent node (e.g., 售前咨询)
      filters.scenario_category = data.label
    } else {
      // Child node (e.g., 尺寸, 材质) - this is issue_type
      filters.issue_type = data.label
    }
  } else if (mode === 'risk') {
    const riskMap: Record<string, string> = { '低风险': 'low', '中风险': 'medium', '高风险': 'high', '极高风险': 'critical' }
    filters.risk_level = riskMap[data.label] || ''
  }
  filters.page = 1
  fetchQAList()
}

// ─── Data Loading ───
async function fetchSummary() {
  try { const { data } = await getQASummary(); summary.value = data } catch {}
}

async function fetchIntents() {
  try { const { data } = await getQAIntents(); intentOptions.value = data.intents || [] } catch {}
}

async function fetchQAList() {
  loading.value = true
  try {
    const params: Record<string, any> = { limit: filters.page_size, offset: (filters.page - 1) * filters.page_size }
    for (const [k, v] of Object.entries(filters)) {
      if (v && k !== 'page' && k !== 'page_size') params[k] = v
    }
    const { data } = await getQAList(params)
    qaList.value = data.items || []; total.value = data.total
  } catch { ElMessage.error('加载问答列表失败') } finally { loading.value = false }
}

// ─── Detail Drawer ───
async function openDetail(id: number) {
  detailLoading.value = true; drawerVisible.value = true; activeTab.value = 'basic'; editMode.value = false
  try {
    const { data } = await getQA(id); currentQA.value = data
    Object.assign(editForm, { ...data })
    const [hRes, pRes, vRes, verRes, sRes] = await Promise.allSettled([
      getQAHealth(id), getQAProduct(id), getQAVariants(id), getQAVersions(id), getQASOP(id),
    ])
    qaHealth.value = hRes.status === 'fulfilled' ? hRes.value.data : null
    qaProduct.value = pRes.status === 'fulfilled' ? pRes.value.data?.product : null
    qaVariants.value = vRes.status === 'fulfilled' ? vRes.value.data?.items || [] : []
    qaVersions.value = verRes.status === 'fulfilled' ? verRes.value.data?.items || [] : []
    qaSOP.value = sRes.status === 'fulfilled' ? sRes.value.data?.sop : null
  } catch { ElMessage.error('加载详情失败') } finally { detailLoading.value = false }
}

async function saveEdit() {
  if ((editForm.risk_level === 'high' || editForm.risk_level === 'critical') && editForm.auto_reply) {
    ElMessage.warning('高/极高风险问答禁止开启“可自动回复”')
    return
  }
  try {
    const { data } = await updateQA(currentQA.value.id, buildQAPayload())
    currentQA.value = data; editMode.value = false; ElMessage.success('保存成功')
    fetchQAList(); fetchSummary()
  } catch (error: any) { ElMessage.error(`保存失败：${formatApiError(error)}`) }
}

function buildQAPayload() {
  const fields = [
    'question', 'answer', 'intent', 'sub_intent',
    'category_l1', 'category_l2', 'category_l3',
    'scenario_category', 'issue_type', 'sop_id',
    'risk_level', 'auto_reply',
    'source_type', 'status', 'product_id',
    'sku_codes', 'keywords',
  ]
  return fields.reduce((payload: Record<string, any>, field) => {
    if (Object.prototype.hasOwnProperty.call(editForm, field)) payload[field] = editForm[field]
    return payload
  }, {})
}

function formatApiError(error: any) {
  const data = error?.response?.data
  if (Array.isArray(data?.errors) && data.errors.length) {
    return data.errors.map((item: any) => item.reason || item.message || item.field).filter(Boolean).join('；')
  }
  return data?.message || data?.error || error?.message || '请检查字段后重试'
}

async function handleSubmitReview() {
  try { await submitQAReview(currentQA.value.id); ElMessage.success('已提交审核'); openDetail(currentQA.value.id); fetchQAList() } catch { ElMessage.error('提交失败') }
}

async function handlePublish() {
  try { await ElMessageBox.confirm('确认发布此问答？', '确认发布') } catch { return }
  try { await publishQA(currentQA.value.id); ElMessage.success('已发布'); openDetail(currentQA.value.id); fetchQAList(); fetchSummary() } catch { ElMessage.error('发布失败') }
}

// Variants
async function handleAddVariant() {
  if (!newVariant.value.trim()) return
  try {
    await addVariant(currentQA.value.id, { variant_text: newVariant.value.trim() })
    const { data } = await getQAVariants(currentQA.value.id); qaVariants.value = data.items || []
    newVariant.value = ''; ElMessage.success('已添加')
  } catch { ElMessage.error('添加失败') }
}

async function handleDeleteVariant(vid: number) {
  try { await removeVariant(currentQA.value.id, vid); qaVariants.value = qaVariants.value.filter((v: any) => v.id !== vid); ElMessage.success('已删除') } catch { ElMessage.error('删除失败') }
}

// Batch
async function batchAction(action: string) {
  if (!selectedIds.value.length) { ElMessage.warning('请先勾选'); return }
  if (['publish', 'archive'].includes(action)) {
    try { await ElMessageBox.confirm(`确定对 ${selectedIds.value.length} 条执行此操作？`, '确认') } catch { return }
  }
  try { await batchUpdateQA(selectedIds.value, action); ElMessage.success('成功'); selectedIds.value = []; fetchQAList(); fetchSummary() } catch { ElMessage.error('失败') }
}

function handleSelectionChange(rows: any[]) { selectedIds.value = rows.map((r: any) => r.id) }

// ─── Helpers ───
function agentStatus(qa: any) {
  if (qa.status !== 'published') return { ok: false, reason: '未发布' }
  if (!qa.auto_reply) return { ok: false, reason: '未开启自动回复' }
  if (qa.risk_level === 'high' || qa.risk_level === 'critical') return { ok: false, reason: '高风险禁止自动回复' }
  return { ok: true, reason: '可安全使用' }
}

function getHealthTags(qa: any) {
  const tags: { text: string; type: string }[] = []
  if (!qa.product_id) tags.push({ text: '缺商品', type: 'warning' })
  if (!(qa.keywords || []).length) tags.push({ text: '缺关键词', type: 'warning' })
  if ((qa.risk_level === 'high' || qa.risk_level === 'critical') && !qa.sop_id) tags.push({ text: '缺SOP', type: 'danger' })
  if ((qa.risk_level === 'high' || qa.risk_level === 'critical') && qa.auto_reply) tags.push({ text: '高风险自动回复', type: 'danger' })
  if (qa.status !== 'published') tags.push({ text: '未发布', type: 'info' })
  return tags
}

function resetFilters() {
  Object.assign(filters, { search: '', intent: '', risk_level: '', status: '', source_type: '', auto_reply: '', scenario_category: '', issue_type: '', category_l1: '', category_l2: '', category_l3: '', sop_status: '', content_contains: '', page: 1 })
  fetchQAList()
}

watch(() => filters, () => {
  const p = new URLSearchParams(); Object.entries(filters).forEach(([k, v]) => { if (v) p.set(k, String(v)) })
  history.replaceState(null, '', `${location.pathname}?${p}`)
}, { deep: true })

watch(navMode, () => fetchNavTree())

function onRiskControlClick(key: string) {
  // 风控面板点击后转为后端分页查询，避免一次性渲染大量数据
  resetFilters()
  if (key === 'high_no_sop') {
    filters.risk_level = 'high,critical'
    filters.sop_status = 'no_sop'
  } else if (key === 'high_auto_reply') {
    filters.risk_level = 'high,critical'
    filters.auto_reply = 'true'
  }
  filters.page = 1
  fetchQAList()
}

onMounted(() => {
  const p = new URLSearchParams(location.search)
  p.forEach((v, k) => { if (k in filters) (filters as any)[k] = v })
  fetchSummary(); fetchIntents(); fetchNavTree(); fetchQAList()
})
</script>

<template>
  <div class="qa-page">
    <!-- Summary Cards -->
    <el-row :gutter="8" class="summary-row">
      <el-col v-for="card in summaryCards" :key="card.key" :span="3">
        <div class="summary-card" :style="{ borderTopColor: card.color }" @click="filterByCard(card.key)">
          <div class="card-value" :style="{ color: card.color }">{{ card.value }}</div>
          <div class="card-label">{{ card.label }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- Main Layout -->
    <el-row :gutter="16" class="main-row">
      <!-- Left: Navigation -->
      <el-col :span="5">
        <div class="nav-panel">
          <div class="nav-header">
            <span style="font-weight:600;font-size:14px">导航</span>
          </div>
          <!-- Nav Mode Tabs -->
          <el-radio-group v-model="navMode" size="small" style="margin-bottom:12px;width:100%">
            <el-radio-button value="scenario">场景</el-radio-button>
            <el-radio-button value="product">类目</el-radio-button>
            <el-radio-button value="risk">风险</el-radio-button>
            <el-radio-button value="control">风控</el-radio-button>
          </el-radio-group>

          <!-- Scenario Tree -->
          <el-tree v-if="navMode==='scenario'" :data="navTree" :props="{ children: 'children', label: 'label' }" node-key="label" :default-expanded-keys="expandedNav" highlight-current v-loading="navLoading" @node-click="(d:any) => onNavClick(d, 'scenario')">
            <template #default="{ data }">
              <div class="nav-node">
                <span class="nav-label">{{ data.label }}</span>
                <span class="nav-stats">
                  <span class="nav-count">{{ data.count }}</span>
                  <el-tag v-if="data.medium_high" size="small" type="warning" class="nav-tag">{{ data.medium_high }}险</el-tag>
                  <el-tag v-if="data.no_sop" size="small" type="danger" class="nav-tag">{{ data.no_sop }}缺SOP</el-tag>
                </span>
              </div>
            </template>
          </el-tree>

          <!-- Product Tree -->
          <el-tree v-if="navMode==='product'" :data="navTree" :props="{ children: 'children', label: 'label' }" node-key="label" highlight-current v-loading="navLoading" @node-click="(d:any) => onNavClick(d, 'product')">
            <template #default="{ data }">
              <div class="nav-node">
                <span class="nav-label">{{ data.label }}</span>
                <span class="nav-stats">
                  <span class="nav-count">{{ data.count }}</span>
                  <el-tag v-if="data.no_agent" size="small" type="danger" class="nav-tag">{{ data.no_agent }}不可用</el-tag>
                </span>
              </div>
            </template>
          </el-tree>

          <!-- Risk Tree -->
          <el-tree v-if="navMode==='risk'" :data="navTree.map((r:any) => ({...r, label: r.label}))" :props="{ children: 'children', label: 'label' }" node-key="label" :default-expanded-keys="['低风险','中风险','高风险','极高风险']" highlight-current v-loading="navLoading" @node-click="(d:any) => onNavClick(d, 'risk')">
            <template #default="{ data }">
              <div class="nav-node">
                <span class="nav-label">{{ data.label }}</span>
                <span class="nav-stats">
                  <span class="nav-count">{{ data.count }}</span>
                  <el-tag v-if="data.no_sop" size="small" type="danger" class="nav-tag">{{ data.no_sop }}缺SOP</el-tag>
                  <el-tag v-if="data.no_review" size="small" type="warning" class="nav-tag">{{ data.no_review }}未审核</el-tag>
                </span>
              </div>
            </template>
          </el-tree>

          <!-- Risk Control Panel -->
          <div v-if="navMode==='control' && riskControl" class="risk-control-panel">
            <div v-for="(section, key) in riskControl" :key="String(key)" class="rc-section" @click="onRiskControlClick(String(key))">
              <div class="rc-header">
                <span class="rc-label">{{ riskControlLabels[key] || key }}</span>
                <el-badge :value="section.count" :type="section.count > 0 ? 'danger' : 'info'" />
              </div>
              <div v-if="section.count > 0" class="rc-hint">点击查看详情</div>
            </div>
          </div>
        </div>
      </el-col>

      <!-- Right: QA List -->
      <el-col :span="19">
        <!-- Filter Bar -->
        <div class="filter-bar">
          <el-input v-model="filters.search" placeholder="搜索问题/答案" clearable size="small" style="width:180px" @clear="fetchQAList" @keyup.enter="fetchQAList" />
          <el-select v-model="filters.risk_level" placeholder="风险" clearable size="small" @change="fetchQAList" style="width:80px">
            <el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="极高" value="critical" />
          </el-select>
          <el-select v-model="filters.status" placeholder="状态" clearable size="small" @change="fetchQAList" style="width:80px">
            <el-option label="已发布" value="published" /><el-option label="草稿" value="draft" /><el-option label="待审核" value="pending_review" />
          </el-select>
          <el-select v-model="filters.auto_reply" placeholder="自动回复" clearable size="small" @change="fetchQAList" style="width:90px">
            <el-option label="可" value="true" /><el-option label="不可" value="false" />
          </el-select>
          <el-button size="small" @click="resetFilters">重置</el-button>
          <div style="flex:1"></div>
          <el-button-group size="small">
            <el-button :type="viewMode==='table'?'primary':''" @click="viewMode='table'"><el-icon><List /></el-icon></el-button>
            <el-button :type="viewMode==='card'?'primary':''" @click="viewMode='card'"><el-icon><Grid /></el-icon></el-button>
          </el-button-group>
          <el-dropdown trigger="click" :disabled="!selectedIds.length">
            <el-button size="small" type="primary" :disabled="!selectedIds.length">批量({{ selectedIds.length }})</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="batchAction('submit_review')">批量提交审核</el-dropdown-item>
                <el-dropdown-item @click="batchAction('publish')">批量发布</el-dropdown-item>
                <el-dropdown-item @click="batchAction('archive')" divided>批量废弃</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <!-- Table View -->
        <el-table v-if="viewMode==='table'" v-loading="loading" :data="qaList" stripe size="small" @selection-change="handleSelectionChange" style="width:100%">
          <el-table-column type="selection" width="36" />
          <el-table-column label="客户问题" min-width="180">
            <template #default="{ row }">
              <a class="qa-link" @click="openDetail(row.id)">{{ row.question }}</a>
              <div class="path-text" v-if="row.scenario_category">{{ row.scenario_category }} / {{ row.issue_type }}</div>
            </template>
          </el-table-column>
          <el-table-column label="答案摘要" min-width="160">
            <template #default="{ row }"><div class="answer-preview">{{ (row.answer||'').slice(0,60) }}...</div></template>
          </el-table-column>
          <el-table-column label="类目" width="120">
            <template #default="{ row }"><div class="cat-text">{{ row.category_l1 }} / {{ row.category_l2 }}</div></template>
          </el-table-column>
          <el-table-column label="风险" width="70"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
          <el-table-column label="自动回复" width="70" align="center">
            <template #default="{ row }"><el-icon v-if="row.auto_reply" color="#67c23a"><CircleCheck /></el-icon><el-icon v-else color="#c0c4cc"><CircleClose /></el-icon></template>
          </el-table-column>
          <el-table-column label="Agent" width="80" align="center">
            <template #default="{ row }"><el-tooltip :content="agentStatus(row).reason"><el-tag :type="agentStatus(row).ok?'success':'danger'" size="small">{{ agentStatus(row).ok?'可用':'不可用' }}</el-tag></el-tooltip></template>
          </el-table-column>
          <el-table-column label="健康" width="120">
            <template #default="{ row }">
              <el-tag v-for="t in getHealthTags(row).slice(0,2)" :key="t.text" size="small" :type="t.type as any" style="margin:1px">{{ t.text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="70"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        </el-table>

        <!-- Card View -->
        <div v-if="viewMode==='card'" v-loading="loading" class="card-grid">
          <el-card v-for="qa in qaList" :key="qa.id" shadow="hover" class="qa-card" @click="openDetail(qa.id)">
            <div class="qc-header">
              <a class="qa-link">{{ qa.question }}</a>
              <el-tooltip :content="agentStatus(qa).reason"><el-tag :type="agentStatus(qa).ok?'success':'danger'" size="small">{{ agentStatus(qa).ok?'可用':'不可用' }}</el-tag></el-tooltip>
            </div>
            <div class="qc-answer">{{ (qa.answer||'').slice(0,100) }}...</div>
            <div class="qc-paths">
              <div class="path-text" v-if="qa.category_l1">商品: {{ qa.category_l1 }} / {{ qa.category_l2 }}{{ qa.category_l3 ? ' / '+qa.category_l3 : '' }}</div>
              <div class="path-text" v-if="qa.scenario_category">场景: {{ qa.scenario_category }} / {{ qa.issue_type }} / <RiskBadge :level="qa.risk_level" /></div>
            </div>
            <div class="qc-meta">
              <el-tag v-if="qa.auto_reply" type="success" size="small">可自动回复</el-tag>
              <StatusTag :status="qa.status" />
            </div>
            <div class="qc-tags">
              <el-tag v-for="t in getHealthTags(qa)" :key="t.text" size="small" :type="t.type as any" style="margin:1px">{{ t.text }}</el-tag>
            </div>
          </el-card>
          <el-empty v-if="!loading && !qaList.length" description="暂无问答数据" />
        </div>

        <!-- Pagination -->
        <div class="pagination-bar">
          <span class="total-text">共 {{ total }} 条</span>
          <el-pagination v-model:current-page="filters.page" :page-size="filters.page_size" :total="total" layout="prev, pager, next" @current-change="fetchQAList" />
        </div>
      </el-col>
    </el-row>

    <!-- Detail Drawer -->
    <el-drawer v-model="drawerVisible" :title="currentQA?.question || '问答详情'" size="70%" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="currentQA">
          <el-alert :title="agentStatus(currentQA).ok ? '可用于 Agent' : '不可用于 Agent'" :type="agentStatus(currentQA).ok ? 'success' : 'warning'" :description="agentStatus(currentQA).reason" show-icon :closable="false" style="margin-bottom:16px" />
          <el-alert v-if="(currentQA.risk_level==='high'||currentQA.risk_level==='critical') && !qaSOP" title="高风险问答缺少 SOP" type="error" description="高风险问答必须关联 SOP，禁止用于 Agent 自动回复" show-icon :closable="false" style="margin-bottom:16px" />

          <el-tabs v-model="activeTab">
            <!-- Tab 1: Basic -->
            <el-tab-pane label="基础问答" name="basic">
              <template v-if="!editMode">
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="客户问题" :span="2">{{ currentQA.question }}</el-descriptions-item>
                  <el-descriptions-item label="标准答案" :span="2"><div class="answer-full">{{ currentQA.answer }}</div></el-descriptions-item>
                  <el-descriptions-item label="意图">{{ currentQA.intent }}</el-descriptions-item>
                  <el-descriptions-item label="风险等级"><RiskBadge :level="currentQA.risk_level" /></el-descriptions-item>
                  <el-descriptions-item label="客服场景">{{ currentQA.scenario_category || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="问题类型">{{ currentQA.issue_type || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="自动回复">{{ currentQA.auto_reply ? '是' : '否' }}</el-descriptions-item>
                  <el-descriptions-item label="状态"><StatusTag :status="currentQA.status" /></el-descriptions-item>
                  <el-descriptions-item label="来源">{{ currentQA.source_type }}</el-descriptions-item>
                </el-descriptions>
                <div style="margin-top:16px;text-align:right">
                  <el-button type="primary" @click="editMode=true">编辑</el-button>
                  <el-button v-if="currentQA.status==='draft'||currentQA.status==='rejected'" type="warning" @click="handleSubmitReview">提交审核</el-button>
                  <el-button v-if="currentQA.status==='pending_review'" type="success" @click="handlePublish">发布</el-button>
                </div>
              </template>
              <template v-else>
                <el-form label-position="top">
                  <el-form-item label="客户问题"><el-input v-model="editForm.question" /></el-form-item>
                  <el-form-item label="标准答案"><el-input v-model="editForm.answer" type="textarea" :rows="6" /></el-form-item>
                  <el-row :gutter="16">
                    <el-col :span="8"><el-form-item label="意图"><el-input v-model="editForm.intent" /></el-form-item></el-col>
                    <el-col :span="8"><el-form-item label="风险等级"><el-select v-model="editForm.risk_level"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="极高" value="critical" /></el-select></el-form-item></el-col>
                    <el-col :span="8"><el-form-item label="客服场景"><el-select v-model="editForm.scenario_category"><el-option v-for="s in ['售前咨询','物流发货','安装指导','售后问题','投诉风险','赔偿纠纷','平台规则','安全质保','推销推荐','特殊场景']" :key="s" :label="s" :value="s" /></el-select></el-form-item></el-col>
                  </el-row>
                  <el-form-item label="可自动回复"><el-switch v-model="editForm.auto_reply" /></el-form-item>
                </el-form>
                <div style="text-align:right"><el-button @click="editMode=false">取消</el-button><el-button type="primary" @click="saveEdit">保存</el-button></div>
              </template>
            </el-tab-pane>

            <!-- Tab 2: Product -->
            <el-tab-pane label="关联商品" name="product">
              <template v-if="qaProduct">
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="商品名称">{{ qaProduct.product_name }}</el-descriptions-item>
                  <el-descriptions-item label="商品编码">{{ qaProduct.i_id }}</el-descriptions-item>
                  <el-descriptions-item label="材质" :class="{'text-danger': (currentQA.answer||'').includes('材质') && !(qaProduct.specs||{}).material}">{{ (qaProduct.specs||{}).material || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="尺寸" :class="{'text-danger': (currentQA.answer||'').includes('尺寸') && !(qaProduct.specs||{}).size}">{{ (qaProduct.specs||{}).size || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="承重">{{ (qaProduct.specs||{}).load_capacity || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="年龄">{{ (qaProduct.specs||{}).age_range || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="质保">{{ (qaProduct.warranty||{}).period || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="物流">{{ (qaProduct.logistics||{}).attribute || '-' }}</el-descriptions-item>
                </el-descriptions>
              </template>
              <el-empty v-else description="未关联商品" />
            </el-tab-pane>

            <!-- Tab 3: Variants -->
            <el-tab-pane label="口语化问法" name="variants">
              <div style="display:flex;gap:8px;margin-bottom:12px">
                <el-input v-model="newVariant" placeholder="输入新的问法" size="small" style="flex:1" @keyup.enter="handleAddVariant" />
                <el-button size="small" type="primary" @click="handleAddVariant">添加</el-button>
              </div>
              <el-table :data="qaVariants" size="small" stripe>
                <el-table-column label="问法" prop="variant_text" min-width="300" />
                <el-table-column label="来源" width="100"><template #default="{ row }"><el-tag size="small" :type="row.source==='ai_generated'?'success':row.source==='imported'?'info':''">{{ row.source==='ai_generated'?'AI':row.source==='imported'?'导入':'人工' }}</el-tag></template></el-table-column>
                <el-table-column label="操作" width="60"><template #default="{ row }"><el-button link type="danger" size="small" @click="handleDeleteVariant(row.id)">删除</el-button></template></el-table-column>
              </el-table>
              <el-empty v-if="!qaVariants.length" description="暂无问法变体" />
            </el-tab-pane>

            <!-- Tab 4: Health + SOP -->
            <el-tab-pane label="风险与健康" name="health">
              <!-- SOP Section -->
              <template v-if="qaSOP">
                <h4 style="margin:0 0 8px">关联 SOP: {{ qaSOP.scenario_code }}</h4>
                <el-descriptions :column="2" border size="small" style="margin-bottom:16px">
                  <el-descriptions-item label="场景">{{ qaSOP.scenario }}</el-descriptions-item>
                  <el-descriptions-item label="风险"><RiskBadge :level="qaSOP.risk_level" /></el-descriptions-item>
                  <el-descriptions-item label="关键词" :span="2"><el-tag v-for="k in (qaSOP.keywords||[]).slice(0,5)" :key="k" size="small" style="margin:2px">{{ k }}</el-tag></el-descriptions-item>
                  <el-descriptions-item label="禁止行为" :span="2"><div v-for="f in qaSOP.forbidden_actions||[]" :key="f" style="color:#f56c6c">- {{ f }}</div></el-descriptions-item>
                  <el-descriptions-item label="标准回复" :span="2"><div class="answer-full">{{ qaSOP.response_template }}</div></el-descriptions-item>
                </el-descriptions>
              </template>
              <el-alert v-else-if="currentQA.risk_level==='high'||currentQA.risk_level==='critical'" title="高风险问答缺少 SOP" type="error" description="此问答为高风险但未关联 SOP，禁止用于 Agent" show-icon :closable="false" style="margin-bottom:16px" />

              <!-- Health Issues -->
              <template v-if="qaHealth">
                <el-row :gutter="16" style="margin-bottom:12px">
                  <el-col :span="8"><div class="stat-mini"><div class="stat-mini-val">{{ qaHealth.variant_count }}</div><div class="stat-mini-lbl">问法变体</div></div></el-col>
                  <el-col :span="8"><div class="stat-mini"><div class="stat-mini-val" :style="{color:qaHealth.total_issues?'#f56c6c':'#67c23a'}">{{ qaHealth.total_issues }}</div><div class="stat-mini-lbl">健康问题</div></div></el-col>
                  <el-col :span="8"><div class="stat-mini"><div class="stat-mini-val"><el-tag :type="qaHealth.can_agent_use?'success':'danger'" size="small">{{ qaHealth.can_agent_use?'可用':'不可用' }}</el-tag></div><div class="stat-mini-lbl">Agent</div></div></el-col>
                </el-row>
                <el-table :data="qaHealth.issues" size="small" stripe>
                  <el-table-column label="严重程度" width="80"><template #default="{ row }"><el-tag :type="row.severity==='critical'?'danger':row.severity==='warning'?'warning':'info'" size="small">{{ row.severity==='critical'?'严重':row.severity==='warning'?'警告':'提示' }}</el-tag></template></el-table-column>
                  <el-table-column label="问题描述" prop="message" min-width="250" />
                </el-table>
              </template>
            </el-tab-pane>

            <!-- Tab 5: Versions -->
            <el-tab-pane label="版本记录" name="versions">
              <el-timeline>
                <el-timeline-item v-for="v in qaVersions" :key="v.id" :timestamp="v.created_at?.replace('T',' ').slice(0,19)" placement="top">
                  <el-card shadow="never"><div><strong>{{ v.action }}</strong> by {{ v.performed_by }}</div><div v-if="v.change_reason" style="color:#909399;font-size:12px;margin-top:4px">{{ v.change_reason }}</div><div v-if="v.changed_fields?.length" style="margin-top:4px"><el-tag v-for="f in v.changed_fields" :key="f" size="small" style="margin:2px">{{ f }}</el-tag></div></el-card>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-if="!qaVersions.length" description="暂无版本记录" />
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.qa-page { padding: 16px; }
.summary-row { margin-bottom: 12px; }
.summary-card { background: #fff; border-radius: 8px; padding: 12px; cursor: pointer; border-top: 3px solid; box-shadow: 0 1px 4px rgba(0,0,0,.06); transition: all .2s; text-align: center; }
.summary-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.1); transform: translateY(-1px); }
.card-value { font-size: 20px; font-weight: 700; }
.card-label { font-size: 11px; color: #909399; margin-top: 2px; }
.main-row { min-height: calc(100vh - 260px); }
.nav-panel { background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); max-height: calc(100vh - 260px); overflow-y: auto; }
.nav-header { margin-bottom: 8px; }
.nav-node { display: flex; align-items: center; justify-content: space-between; width: 100%; font-size: 13px; }
.nav-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nav-stats { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.nav-count { color: #909399; font-size: 11px; }
.nav-tag { transform: scale(0.75); }
.filter-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; background: #fff; padding: 10px 12px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.06); flex-wrap: wrap; }
.qa-link { color: #409eff; cursor: pointer; font-weight: 500; font-size: 13px; }
.qa-link:hover { text-decoration: underline; }
.answer-preview { font-size: 12px; color: #606266; }
.path-text { font-size: 11px; color: #909399; margin-top: 2px; }
.card-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
.qa-card { cursor: pointer; transition: all .2s; }
.qa-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.12); }
.qc-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; }
.qc-answer { font-size: 12px; color: #606266; line-height: 1.5; margin-bottom: 6px; }
.qc-paths { margin-bottom: 6px; }
.qc-meta { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.qc-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.pagination-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; }
.total-text { font-size: 13px; color: #909399; }
.answer-full { white-space: pre-wrap; line-height: 1.6; max-height: 200px; overflow-y: auto; }
.text-danger { color: #f56c6c; font-weight: bold; }
.stat-mini { background: #fff; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.stat-mini-val { font-size: 20px; font-weight: 700; color: #303133; }
.stat-mini-lbl { font-size: 11px; color: #909399; margin-top: 2px; }
.cat-text { font-size: 12px; }
.risk-control-panel { margin-top: 4px; }
.rc-section { padding: 10px 12px; margin-bottom: 4px; border-radius: 6px; cursor: pointer; background: #fff; border: 1px solid #ebeef5; transition: all .2s; }
.rc-section:hover { border-color: #409eff; background: #f0f7ff; }
.rc-header { display: flex; justify-content: space-between; align-items: center; }
.rc-label { font-size: 13px; font-weight: 500; }
.rc-hint { font-size: 11px; color: #909399; margin-top: 2px; }
</style>
