<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProducts, getProductSummary, getProductCategoryTree,
  getProduct, getProductHealth, getProductVersions,
  createProduct, updateProduct, submitProductReview, publishProduct, batchUpdateProducts,
  getProductQA, createProductQA, linkProductQA, unlinkProductQA,
  linkProductMedia, unlinkProductMedia,
} from '../api/product'
import {
  getQAList, createQA, updateQA, deleteQA,
} from '../api/qa'
import {
  getMediaAssets, updateMedia, deleteMedia, importDingtalkReport, uploadMediaAsset, batchUpdateMediaTags,
  ASSET_TYPE_LABELS, STATUS_LABELS, STATUS_TAG_TYPES, RISK_LEVEL_OPTIONS, SOURCE_TYPE_OPTIONS,
  MEDIA_PURPOSE_OPTIONS, APPLICABLE_STYLE_TYPE_OPTIONS, ANSWER_SCENARIO_OPTIONS, AUTO_SEND_LEVEL_OPTIONS,
  getMediaPurpose, getApplicableStyle, getAnswerScenarios, getAutoSendLevel, getMediaPurposeLabel,
  buildMediaUpdatePayload,
  type MediaAsset,
} from '../api/media'
import StatusTag from '../components/common/StatusTag.vue'
import RiskBadge from '../components/common/RiskBadge.vue'
import BatchQAManager from '../components/batch/BatchQAManager.vue'
import BatchMediaTagManager from '../components/batch/BatchMediaTagManager.vue'

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
  status: '', agent_usable: '', has_qa: '', missing_field: '', high_risk: '',
  sort_by: 'updated_at', sort_order: 'desc',
  page: 1, page_size: 20,
})

const specDefaults = {
  material: '', size: '', load_capacity: '', age_range: '', accessories: '', install_method: '',
  detachable: '', drill_required: '', installation_time: '', installation_difficulty: '',
  rental_friendly: '', pinch_safety: '', stability_note: '', moisture: '', cleaning: '', odor_note: '',
  certification_report: '', size_image_note: '', install_video_note: '', package_list_note: '', certificate_note: '',
}
const logisticsDefaults = { attribute: '', shipping_note: '', remote_area_note: '' }
const warrantyDefaults = { period: '', scope: '', exclusion: '' }

function makeSpecs(extra: Record<string, any> = {}) { return { ...specDefaults, ...(extra || {}) } }
function makeLogistics(extra: Record<string, any> = {}) { return { ...logisticsDefaults, ...(extra || {}) } }
function makeWarranty(extra: Record<string, any> = {}) { return { ...warrantyDefaults, ...(extra || {}) } }

const advancedSpecGroups = [
  {
    title: '安装/结构',
    fields: [
      { key: 'detachable', label: '是否可拆卸', placeholder: '例如：可拆卸；抽屉可单独取出；柜体不可拆' },
      { key: 'drill_required', label: '是否需要打孔', placeholder: '例如：免打孔；需打孔固定；租房可用' },
      { key: 'installation_time', label: '安装耗时', placeholder: '例如：约20-30分钟' },
      { key: 'installation_difficulty', label: '安装难度', placeholder: '例如：简单，按说明书安装即可' },
      { key: 'rental_friendly', label: '租房/墙面友好', placeholder: '例如：免打孔，不伤墙面' },
    ],
  },
  {
    title: '安全/养护',
    fields: [
      { key: 'pinch_safety', label: '防夹/安全设计', placeholder: '例如：防夹滑轨/圆角设计；没有明确资料请留空' },
      { key: 'stability_note', label: '稳定性说明', placeholder: '例如：建议靠墙摆放；需固定防倾倒' },
      { key: 'moisture', label: '防潮/受潮说明', placeholder: '例如：表面可擦拭，避免长期泡水' },
      { key: 'cleaning', label: '清洁保养', placeholder: '例如：湿布擦拭，避免强腐蚀清洁剂' },
      { key: 'odor_note', label: '气味说明', placeholder: '例如：新包装拆开后建议通风' },
      { key: 'certification_report', label: '合格证/质检资料', placeholder: '仅填写已确认的证书、报告或页面公示；不要编造编号' },
    ],
  },
  {
    title: '图片/视频对应说明',
    fields: [
      { key: 'size_image_note', label: '尺寸图说明', placeholder: '例如：尺寸图可回答尺寸、是否可拆卸、抽屉结构' },
      { key: 'install_video_note', label: '安装视频说明', placeholder: '例如：安装视频适合回答安装步骤、是否需要工具' },
      { key: 'package_list_note', label: '包装/配件图说明', placeholder: '例如：可核对配件、赠品、底板数量' },
      { key: 'certificate_note', label: '证书图片说明', placeholder: '例如：可发送合格证图片，但安全承诺以证书内容为准' },
    ],
  },
]

const importantProductFields = [
  { path: 'specs.material', label: '材质' },
  { path: 'specs.size', label: '尺寸' },
  { path: 'specs.detachable', label: '是否可拆卸' },
  { path: 'specs.drill_required', label: '是否打孔' },
  { path: 'specs.install_method', label: '安装方式' },
  { path: 'specs.accessories', label: '配件清单' },
  { path: 'specs.pinch_safety', label: '安全/防夹说明' },
  { path: 'specs.certification_report', label: '合格证/质检资料' },
  { path: 'warranty.period', label: '质保期' },
  { path: 'logistics.attribute', label: '物流属性' },
]

const builtinSceneTagOptions = [
  { value: 'dimensions', label: '尺寸' },
  { value: 'detachable', label: '可拆卸' },
  { value: 'installation', label: '安装' },
  { value: 'accessories', label: '配件' },
  { value: 'package_list', label: '包装清单' },
  { value: 'certification_report', label: '证书/质检' },
  { value: 'color', label: '颜色外观' },
  { value: 'material', label: '材质' },
]

const customSceneTags = ref<string[]>([])
try {
  const saved = localStorage.getItem('kb_custom_scene_tags')
  if (saved) customSceneTags.value = JSON.parse(saved)
} catch { customSceneTags.value = [] }

const sceneTagOptions = computed(() => {
  const custom = customSceneTags.value.map((t) => ({ value: t, label: t }))
  return [...builtinSceneTagOptions, ...custom]
})

// Drawer
const drawerVisible = ref(false)
const activeTab = ref('basic')
const currentProduct = ref<any>(null)
const productHealth = ref<any>(null)
const productVersions = ref<any[]>([])
const productMediaAssets = ref<MediaAsset[]>([])
const editMode = ref(false)
const editForm = reactive<any>({})
const detailLoading = ref(false)
const mediaLoading = ref(false)
const newCustomSceneTag = ref('')
const createDialogVisible = ref(false)
const createForm = reactive<any>({
  product_name: '', i_id: '', brand: 'INHE',
  category_l1: '', category_l2: '', category_l3: '',
  specs: makeSpecs(), warranty: makeWarranty(), logistics: makeLogistics(),
})

// 关联 QA
const productQA = ref<any[]>([])
const qaSearch = ref('')
const qaRiskFilter = ref('')
const qaLinkDialogVisible = ref(false)
const qaLinkSearch = ref('')
const qaLinkLoading = ref(false)
const qaLinkCandidates = ref<any[]>([])
const qaCreateDialogVisible = ref(false)
const qaCreateForm = reactive<any>({
  question: '', answer: '', intent: 'general', risk_level: 'low', auto_reply: true,
})
const qaCategoryDialogVisible = ref(false)
const qaCategoryForm = reactive<any>({
  question: '', answer: '', intent: 'general', risk_level: 'low', auto_reply: false,
})

// 批量 QA
const selectedQA = ref<any[]>([])
const batchQADialogVisible = ref(false)
const batchQAField = ref<'risk_level' | 'auto_reply' | 'status'>('risk_level')
const batchQAValue = ref<any>('')

// 批量素材标签（本商品）
const batchMediaDialogVisible = ref(false)
const batchMediaMode = ref<'add' | 'remove'>('add')
const batchMediaTag = ref('')

// 按类目批量管理
const batchQAManagerVisible = ref(false)
const batchMediaTagManagerVisible = ref(false)

// 素材关联
const mediaLinkDialogVisible = ref(false)
const mediaLinkSearch = ref('')
const mediaLinkType = ref('')
const mediaLinkLoading = ref(false)
const mediaLinkCandidates = ref<MediaAsset[]>([])

const isSupervisor = computed(() => {
  const role = localStorage.getItem('kb_user_role') || 'supervisor'
  return role !== 'operator'
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
  filters.status = ''; filters.agent_usable = ''; filters.has_qa = ''; filters.missing_field = ''; filters.high_risk = ''
  if (key === 'published') filters.status = 'published'
  else if (key === 'incomplete') filters.missing_field = 'incomplete'
  else if (key === 'review') filters.status = 'pending_review'
  else if (key === 'agent_ok') filters.agent_usable = 'yes'
  else if (key === 'agent_no') filters.agent_usable = 'no'
  else if (key === 'no_qa') filters.has_qa = 'no'
  else if (key === 'high_risk') filters.high_risk = 'yes'
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
async function fetchSummary() { try { const { data } = await getProductSummary(); summary.value = data } catch {} }
async function fetchCategoryTree() { try { const { data } = await getProductCategoryTree(); categoryTree.value = data } catch {} }

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
    if (filters.agent_usable) params.agent_usable = filters.agent_usable
    if (filters.has_qa) params.has_qa = filters.has_qa
    if (filters.missing_field) params.missing_field = filters.missing_field
    if (filters.high_risk) params.high_risk = filters.high_risk
    const { data } = await getProducts(params)
    let items = data.items || []
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
      specs: makeSpecs(data.specs || {}), logistics: makeLogistics(data.logistics || {}), warranty: makeWarranty(data.warranty || {}),
    })
    const [healthRes, versionsRes] = await Promise.allSettled([
      getProductHealth(id), getProductVersions(id),
    ])
    productHealth.value = healthRes.status === 'fulfilled' ? healthRes.value.data : null
    productVersions.value = versionsRes.status === 'fulfilled' ? versionsRes.value.data.items || [] : []
    fetchProductMedia(data)
    fetchProductQA(data)
  } catch { ElMessage.error('加载详情失败') } finally { detailLoading.value = false }
}

function getPathValue(source: any, path: string) {
  return path.split('.').reduce((obj, key) => (obj ? obj[key] : undefined), source)
}
function hasUsefulValue(value: any) {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  const text = String(value).trim()
  return Boolean(text) && text !== '-' && text !== '详见商品详情页'
}

const currentProductMissingFields = computed(() => {
  if (!currentProduct.value) return []
  const backendMissing = currentProduct.value.missing_fields
  if (Array.isArray(backendMissing) && backendMissing.length) return backendMissing
  return importantProductFields.filter((field) => !hasUsefulValue(getPathValue(currentProduct.value, field.path))).map((f) => f.label)
})

const productCardCompleteness = computed(() => {
  if (!currentProduct.value) return 0
  return Math.round(currentProduct.value.completeness_score || 0)
})

// ─── Media Assets ───
const mediaPurposeOrder = [
  'appearance_image', 'size_image', 'install_image', 'install_video',
  'packing_list_image', 'accessory_image', 'certificate_image', 'material_image', 'aftersales_image', 'other',
]

const groupedMediaAssets = computed(() => {
  const groups: Record<string, MediaAsset[]> = {}
  productMediaAssets.value.forEach((asset) => {
    const purpose = getMediaPurpose(asset)
    if (!groups[purpose]) groups[purpose] = []
    groups[purpose].push(asset)
  })
  return Object.entries(groups).sort((a, b) => {
    const ia = mediaPurposeOrder.indexOf(a[0]); const ib = mediaPurposeOrder.indexOf(b[0])
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })
})

function ensureAssetSourceRaw(asset: MediaAsset) {
  if (!asset.source_raw || typeof asset.source_raw !== 'object') asset.source_raw = {}
  return asset.source_raw
}

function normalizeAssetCardFields(asset: MediaAsset) {
  const sr = ensureAssetSourceRaw(asset)
  // 素材用途
  sr.media_purpose = getMediaPurpose(asset)
  // 适用款式
  const style = getApplicableStyle(asset)
  sr.applicable_style = {
    scope_type: style.scope_type || 'all',
    scope_values: style.scope_values || [],
    scope_note: style.scope_note || '',
  }
  // 可回答问题
  sr.answer_scenarios = getAnswerScenarios(asset)
  // 自动发送等级
  sr.auto_send_level = getAutoSendLevel(asset)
}

async function fetchProductMedia(product = currentProduct.value) {
  if (!product) return
  mediaLoading.value = true
  try {
    const params: Record<string, any> = { limit: 200 }
    if (product.id) params.product_id = product.id
    if (product.i_id) params.i_id = product.i_id
    if (product.product_name) params.product_name = product.product_name
    const { data } = await getMediaAssets(params)
    productMediaAssets.value = (data.items || []).map((a: MediaAsset) => {
      normalizeAssetCardFields(a)
      return a
    })
  } catch {
    productMediaAssets.value = []
    ElMessage.warning('加载当前商品素材失败')
  } finally { mediaLoading.value = false }
}

// ─── 关联 QA ───
async function fetchProductQA(product = currentProduct.value) {
  if (!product || !product.id) return
  try {
    const { data } = await getProductQA(product.id)
    productQA.value = data.items || []
  } catch {
    productQA.value = []
  }
}

const filteredQA = computed(() => {
  let list = productQA.value
  if (qaSearch.value) list = list.filter((q: any) => q.question.includes(qaSearch.value) || q.answer.includes(qaSearch.value))
  if (qaRiskFilter.value) list = list.filter((q: any) => q.risk_level === qaRiskFilter.value)
  return list
})

async function openQALinkDialog() {
  qaLinkDialogVisible.value = true
  qaLinkSearch.value = ''
  qaLinkCandidates.value = []
  await searchQALinkCandidates()
}

async function searchQALinkCandidates() {
  qaLinkLoading.value = true
  try {
    const params: Record<string, any> = { limit: 50, status: '' }
    if (qaLinkSearch.value) params.search = qaLinkSearch.value
    const { data } = await getQAList(params)
    const linkedIds = new Set(productQA.value.map((q: any) => q.id))
    qaLinkCandidates.value = (data.items || []).filter((q: any) => !linkedIds.has(q.id))
  } catch {
    qaLinkCandidates.value = []
  } finally { qaLinkLoading.value = false }
}

async function confirmLinkQA(qa: any) {
  if (!currentProduct.value) return
  try {
    await linkProductQA(currentProduct.value.id, qa.id)
    ElMessage.success('关联问答成功')
    await fetchProductQA(currentProduct.value)
    await searchQALinkCandidates()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '关联失败')
  }
}

async function unlinkQA(qa: any) {
  if (!currentProduct.value) return
  try {
    await ElMessageBox.confirm('取消关联后该问答不再归属当前商品，是否继续？', '提示', { type: 'warning' })
    await unlinkProductQA(currentProduct.value.id, qa.id)
    ElMessage.success('已取消关联')
    await fetchProductQA(currentProduct.value)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '取消关联失败')
  }
}

function openQACreateDialog() {
  qaCreateDialogVisible.value = true
  Object.assign(qaCreateForm, { question: '', answer: '', intent: 'general', risk_level: 'low', auto_reply: true })
}

async function saveQACreate() {
  if (!currentProduct.value) return
  if (!qaCreateForm.question.trim() || !qaCreateForm.answer.trim()) {
    ElMessage.warning('请填写问题和答案')
    return
  }
  try {
    await createProductQA(currentProduct.value.id, { ...qaCreateForm })
    ElMessage.success('问答已创建并关联')
    qaCreateDialogVisible.value = false
    await fetchProductQA(currentProduct.value)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '创建失败')
  }
}

function openQACategoryDialog() {
  qaCategoryDialogVisible.value = true
  Object.assign(qaCategoryForm, { question: '', answer: '', intent: 'general', risk_level: 'low', auto_reply: false })
}

async function saveQACategory() {
  if (!currentProduct.value) return
  if (!qaCategoryForm.question.trim() || !qaCategoryForm.answer.trim()) {
    ElMessage.warning('请填写问题和答案')
    return
  }
  try {
    await createQA({
      ...qaCategoryForm,
      product_id: null,
      category_l1: currentProduct.value.category_l1 || '',
      category_l2: currentProduct.value.category_l2 || '',
      category_l3: currentProduct.value.category_l3 || '',
      status: 'draft',
    })
    ElMessage.success('类目问答已创建')
    qaCategoryDialogVisible.value = false
    await fetchProductQA(currentProduct.value)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '创建失败')
  }
}

function handleQASelectionChange(rows: any[]) {
  selectedQA.value = rows
}

function openBatchQADialog(field: 'risk_level' | 'auto_reply' | 'status') {
  if (!selectedQA.value.length) {
    ElMessage.warning('请先勾选要批量修改的问答')
    return
  }
  batchQAField.value = field
  batchQAValue.value = field === 'risk_level' ? 'low' : field === 'auto_reply' ? true : 'draft'
  batchQADialogVisible.value = true
}

async function applyBatchQA() {
  if (!selectedQA.value.length) return
  const payload: Record<string, any> = { [batchQAField.value]: batchQAValue.value }
  try {
    await Promise.all(selectedQA.value.map((q) => updateQA(q.id, payload)))
    ElMessage.success(`已批量更新 ${selectedQA.value.length} 条问答的${batchQAField.value === 'risk_level' ? '风险等级' : batchQAField.value === 'auto_reply' ? '自动回复' : '状态'}`)
    batchQADialogVisible.value = false
    await fetchProductQA()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '批量更新失败')
  }
}

async function batchUnlinkQA() {
  if (!selectedQA.value.length || !currentProduct.value) return
  const productSpecific = selectedQA.value.filter((q) => q.product_id === currentProduct.value!.id)
  if (!productSpecific.length) {
    ElMessage.warning('选中的问答均为类目问答，无法对当前商品单独取消关联')
    return
  }
  try {
    await ElMessageBox.confirm(`确定对 ${productSpecific.length} 条商品问答取消关联？`, '批量取消关联', { type: 'warning' })
    await Promise.all(productSpecific.map((q) => unlinkProductQA(currentProduct.value!.id, q.id)))
    ElMessage.success('已批量取消关联')
    await fetchProductQA()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '批量取消关联失败')
  }
}

async function batchDeleteQA() {
  if (!selectedQA.value.length) return
  try {
    await ElMessageBox.confirm(`确定删除 ${selectedQA.value.length} 条问答？删除后不可恢复。`, '批量删除', { type: 'warning' })
    await Promise.all(selectedQA.value.map((q) => deleteQA(q.id)))
    ElMessage.success('已批量删除')
    await fetchProductQA()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '批量删除失败')
  }
}

function openBatchMediaDialog(mode: 'add' | 'remove') {
  batchMediaMode.value = mode
  batchMediaTag.value = ''
  batchMediaDialogVisible.value = true
}

async function applyBatchMediaTag() {
  const tag = batchMediaTag.value.trim()
  if (!tag) {
    ElMessage.warning('请输入或选择标签')
    return
  }
  const ids = productMediaAssets.value.map((a) => a.id)
  if (!ids.length) return
  try {
    const { data } = await batchUpdateMediaTags(ids, batchMediaMode.value === 'add' ? [tag] : [], batchMediaMode.value === 'remove' ? [tag] : [])
    ElMessage.success(`已${batchMediaMode.value === 'add' ? '添加' : '移除'} ${data.updated} 条素材的标签`)
    batchMediaDialogVisible.value = false
    await fetchProductMedia()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '批量标签失败')
  }
}

function addSceneTag(row: MediaAsset, tag: string) {
  const tags = new Set(row.scene_tags || [])
  tags.add(tag)
  row.scene_tags = Array.from(tags)
}

function addAnswerScenario(row: MediaAsset, scenario: string) {
  const sr = ensureAssetSourceRaw(row)
  const scenarios = new Set((sr.answer_scenarios || []) as string[])
  scenarios.add(scenario)
  sr.answer_scenarios = Array.from(scenarios)
}

function addCustomSceneTag() {
  const tag = newCustomSceneTag.value.trim()
  if (!tag) return
  if (!customSceneTags.value.includes(tag)) {
    customSceneTags.value.push(tag)
    localStorage.setItem('kb_custom_scene_tags', JSON.stringify(customSceneTags.value))
  }
  newCustomSceneTag.value = ''
}

function isMediaExpired(row: MediaAsset) {
  if (row.refresh_status === 'needs_refresh') return true
  const url = row.asset_url || ''
  const m = url.match(/[?&]Expires=(\\d+)/)
  if (m) {
    const ts = parseInt(m[1], 10)
    if (!isNaN(ts)) return Date.now() > ts * 1000
  }
  return false
}

async function saveMedia(row: MediaAsset) {
  try {
    const { data } = await updateMedia(row.id, buildMediaUpdatePayload(row))
    ElMessage.success('素材已保存')
    // 用返回的最新数据局部更新，避免全量刷新导致的慢/闪屏
    const saved = data.asset as MediaAsset
    normalizeAssetCardFields(saved)
    const idx = productMediaAssets.value.findIndex((a) => a.id === saved.id)
    if (idx >= 0) {
      productMediaAssets.value[idx] = saved
    } else {
      productMediaAssets.value.push(saved)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存素材失败')
  }
}

async function approveMediaForAgent(row: MediaAsset) {
  row.status = 'approved'
  row.usable_for_agent = true
  await saveMedia(row)
}

async function removeMedia(row: MediaAsset) {
  try {
    await ElMessageBox.confirm('删除后素材将从素材库移除，是否继续？', '删除素材', { type: 'warning' })
    await deleteMedia(row.id)
    ElMessage.success('素材已删除')
    await fetchProductMedia()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '删除失败')
  }
}

async function refreshDingtalkMedia() {
  try {
    await ElMessageBox.confirm('将从今日钉钉媒体报告导入/更新素材，是否继续？', '刷新钉钉素材', { type: 'info' })
    const { data } = await importDingtalkReport('data/dingtalk_media_report_daily.json')
    ElMessage.success(`刷新完成：新增 ${data.stats?.new_assets ?? 0}，更新 ${data.stats?.updated_assets ?? 0}`)
    await fetchProductMedia()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '刷新失败')
  }
}

async function handleMediaUpload(options: any) {
  if (!currentProduct.value) return
  const file = options.file
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  const isVideo = ['mp4', 'webm', 'mov'].includes(ext)
  const assetType = isVideo ? 'install_video' : 'sku_image'

  const formData = new FormData()
  formData.append('file', file)
  formData.append('product_id', String(currentProduct.value.id))
  if (currentProduct.value.i_id) formData.append('i_id', currentProduct.value.i_id)
  if (currentProduct.value.product_name) formData.append('product_name', currentProduct.value.product_name)
  formData.append('asset_type', assetType)
  formData.append('asset_title', file.name)
  formData.append('scene_tags', JSON.stringify([]))

  try {
    const { data } = await uploadMediaAsset(formData)
    ElMessage.success('素材上传成功')
    const uploaded = data.asset as MediaAsset
    normalizeAssetCardFields(uploaded)
    productMediaAssets.value.push(uploaded)
    if (options.onSuccess) options.onSuccess()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '上传失败')
    if (options.onError) options.onError(e)
  }
}

// ─── 关联素材 ───
async function openMediaLinkDialog() {
  mediaLinkDialogVisible.value = true
  mediaLinkSearch.value = ''
  mediaLinkType.value = ''
  mediaLinkCandidates.value = []
  await searchMediaLinkCandidates()
}

async function searchMediaLinkCandidates() {
  mediaLinkLoading.value = true
  try {
    const params: Record<string, any> = { limit: 50 }
    if (mediaLinkSearch.value) params.keyword = mediaLinkSearch.value
    if (mediaLinkType.value) params.asset_type = mediaLinkType.value
    const { data } = await getMediaAssets(params)
    const linkedIds = new Set(productMediaAssets.value.map((m) => m.id))
    mediaLinkCandidates.value = (data.items || []).filter((m: MediaAsset) => !linkedIds.has(m.id))
  } catch { mediaLinkCandidates.value = [] } finally { mediaLinkLoading.value = false }
}

async function confirmLinkMedia(asset: MediaAsset) {
  if (!currentProduct.value) return
  try {
    await linkProductMedia(currentProduct.value.id, asset.id)
    ElMessage.success('素材关联成功')
    await fetchProductMedia()
    await searchMediaLinkCandidates()
  } catch (e: any) { ElMessage.error(e?.response?.data?.error || '关联失败') }
}

async function unlinkMedia(asset: MediaAsset) {
  if (!currentProduct.value) return
  try {
    await ElMessageBox.confirm('取消关联后该素材不再归属当前商品，是否继续？', '提示', { type: 'warning' })
    await unlinkProductMedia(currentProduct.value.id, asset.id)
    ElMessage.success('已取消关联')
    await fetchProductMedia()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '取消关联失败')
  }
}

async function saveEdit() {
  try {
    const { data } = await updateProduct(currentProduct.value.id, editForm)
    currentProduct.value = data; editMode.value = false; ElMessage.success('保存成功')
    fetchProducts(); fetchSummary()
  } catch { ElMessage.error('保存失败') }
}

function resetCreateForm() {
  Object.assign(createForm, {
    product_name: '', i_id: '', brand: 'INHE',
    category_l1: '', category_l2: '', category_l3: '',
    specs: makeSpecs(), warranty: makeWarranty(), logistics: makeLogistics(),
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
    await fetchProducts(); await fetchSummary()
    openDetail(data.id)
  } catch (e: any) { ElMessage.error(e?.response?.data?.error || '新增商品失败') }
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
  Object.assign(filters, { search: '', category_l1: '', category_l2: '', category_l3: '', status: '', agent_usable: '', has_qa: '', missing_field: '', high_risk: '', sort_by: 'updated_at', sort_order: 'desc', page: 1 })
  fetchProducts()
}

watch(() => filters, () => {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, String(v)) })
  history.replaceState(null, '', `${location.pathname}?${params}`)
}, { deep: true })

onMounted(() => {
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
        <router-link :to="{ name: 'rag' }" style="color:#409eff;font-weight:600">RAG 知识条目</router-link>
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
          <el-button size="small" @click="batchQAManagerVisible = true">批量管理关联问答</el-button>
          <el-button size="small" @click="batchMediaTagManagerVisible = true">批量管理素材标签</el-button>
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
    <el-drawer v-model="drawerVisible" :title="currentProduct?.product_name || '商品详情'" size="72%" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="currentProduct">
          <!-- Header: Agent status + health + latest version -->
          <div class="detail-header">
            <div class="detail-meta">
              <el-tag :type="currentProduct.status==='published'?'success':currentProduct.status==='pending_review'?'warning':'info'" size="small">{{ currentProduct.status }}</el-tag>
              <span class="meta-item">编码: {{ currentProduct.i_id }}</span>
              <span class="meta-item">类目: {{ currentProduct.category_l1 }}{{ currentProduct.category_l2 ? ' / ' + currentProduct.category_l2 : '' }}</span>
              <span class="meta-item">版本: v{{ currentProduct.version || 1 }}</span>
            </div>
            <div class="detail-health">
              <div class="dh-score" :style="{ color: completenessColor(productCardCompleteness) }">{{ productCardCompleteness }}%</div>
              <div class="dh-label">完整度</div>
            </div>
          </div>

          <el-alert v-if="productHealth" :title="productHealth.can_agent_use ? '此商品可用于智能客服 Agent' : '此商品暂不可用于 Agent'" :type="productHealth.can_agent_use ? 'success' : 'warning'" :description="productHealth.agent_block_reason || agentBlockReason(currentProduct)" show-icon :closable="false" style="margin-bottom:12px" />

          <el-alert v-if="productVersions.length" type="info" :closable="false" show-icon style="margin-bottom:12px">
            <template #title>
              最近变更：{{ productVersions[0].action }} by {{ productVersions[0].performed_by }} · {{ productVersions[0].created_at?.replace('T',' ').slice(0,19) }}
              <span v-if="productVersions[0].changed_fields?.length" style="margin-left:8px">
                <el-tag v-for="f in productVersions[0].changed_fields" :key="f" size="small" style="margin:0 2px">{{ f }}</el-tag>
              </span>
            </template>
          </el-alert>

          <el-tabs v-model="activeTab" type="border-card">
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
                <div class="product-card-health">
                  <div>
                    <div class="health-title">商品卡片完整度 {{ productCardCompleteness }}%</div>
                    <div class="health-desc">商品事实尽量维护在这里，问答资料只保留通用话术和政策模板。</div>
                  </div>
                  <div class="missing-chips">
                    <el-tag v-for="field in currentProductMissingFields" :key="field" type="warning" size="small">缺{{ field }}</el-tag>
                    <el-tag v-if="!currentProductMissingFields.length" type="success" size="small">关键字段已补齐</el-tag>
                  </div>
                </div>
                <template v-for="group in advancedSpecGroups" :key="group.title">
                  <el-divider content-position="left">{{ group.title }}</el-divider>
                  <el-descriptions :column="2" border size="small">
                    <el-descriptions-item v-for="field in group.fields" :key="field.key" :label="field.label">{{ (currentProduct.specs || {})[field.key] || '-' }}</el-descriptions-item>
                  </el-descriptions>
                </template>
                <el-divider content-position="left">售后/物流补充</el-divider>
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="质保范围">{{ (currentProduct.warranty||{}).scope || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="质保例外">{{ (currentProduct.warranty||{}).exclusion || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="发货说明">{{ (currentProduct.logistics||{}).shipping_note || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="偏远地区说明">{{ (currentProduct.logistics||{}).remote_area_note || '-' }}</el-descriptions-item>
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
                    <el-col :span="24">
                      <el-alert title="高频追问资料" description="这里维护的是商品事实，不需要把每种问法都写成问答。AI 会按买家意图从这些字段和素材标签里组合回复。" type="info" :closable="false" show-icon style="margin:4px 0 12px" />
                    </el-col>
                    <template v-for="group in advancedSpecGroups" :key="group.title">
                      <el-col :span="24"><el-divider content-position="left">{{ group.title }}</el-divider></el-col>
                      <el-col v-for="field in group.fields" :key="field.key" :span="12">
                        <el-form-item :label="field.label">
                          <el-input v-model="editForm.specs[field.key]" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" :placeholder="field.placeholder" />
                        </el-form-item>
                      </el-col>
                    </template>
                    <el-col :span="24"><el-divider content-position="left">售后/物流补充</el-divider></el-col>
                    <el-col :span="12"><el-form-item label="质保范围"><el-input v-model="editForm.warranty.scope" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="质保例外"><el-input v-model="editForm.warranty.exclusion" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="发货说明"><el-input v-model="editForm.logistics.shipping_note" /></el-form-item></el-col>
                    <el-col :span="12"><el-form-item label="偏远地区说明"><el-input v-model="editForm.logistics.remote_area_note" /></el-form-item></el-col>
                  </el-row>
                </el-form>
                <div style="text-align:right"><el-button @click="editMode=false">取消</el-button><el-button type="primary" @click="saveEdit">保存</el-button></div>
              </template>
            </el-tab-pane>

            <!-- Tab 2: Related QA -->
            <el-tab-pane label="关联问答" name="qa">
              <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap">
                <el-input v-model="qaSearch" placeholder="搜索问答" clearable size="small" style="width:200px" />
                <el-select v-model="qaRiskFilter" placeholder="风险等级" clearable size="small" style="width:100px">
                  <el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="极高" value="critical" />
                </el-select>
                <div style="flex:1"></div>
                <el-dropdown v-if="selectedQA.length" size="small" split-button type="primary" @click="openBatchQADialog('risk_level')">
                  批量修改
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item @click="openBatchQADialog('risk_level')">批量设置风险等级</el-dropdown-item>
                      <el-dropdown-item @click="openBatchQADialog('auto_reply')">批量设置自动回复</el-dropdown-item>
                      <el-dropdown-item @click="openBatchQADialog('status')">批量设置状态</el-dropdown-item>
                      <el-dropdown-item divided @click="batchUnlinkQA">批量取消关联</el-dropdown-item>
                      <el-dropdown-item @click="batchDeleteQA" style="color:#f56c6c">批量删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button size="small" type="primary" @click="openQACreateDialog">新增商品问答</el-button>
                <el-button size="small" @click="openQALinkDialog">关联已有问答</el-button>
                <el-button size="small" type="warning" @click="openQACategoryDialog">新增类目问答</el-button>
                <span style="font-size:12px;color:#909399">共 {{ filteredQA.length }} 条</span>
              </div>
              <el-table :data="filteredQA" size="small" stripe @selection-change="handleQASelectionChange">
                <el-table-column type="selection" width="36" />
                <el-table-column label="客户问题" prop="question" min-width="180" show-overflow-tooltip />
                <el-table-column label="答案摘要" min-width="180"><template #default="{ row }">{{ (row.answer||'').slice(0,80) }}{{ (row.answer||'').length > 80 ? '...' : '' }}</template></el-table-column>
                <el-table-column label="意图" prop="intent" width="100" />
                <el-table-column label="风险" width="70"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
                <el-table-column label="自动回复" width="70" align="center"><template #default="{ row }"><el-icon v-if="row.auto_reply" color="#67c23a"><CircleCheck /></el-icon><el-icon v-else color="#909399"><CircleClose /></el-icon></template></el-table-column>
                <el-table-column label="归属" width="100"><template #default="{ row }"><el-tag v-if="row.product_id === currentProduct?.id" size="small" type="success">当前商品</el-tag><el-tag v-else size="small" type="warning">类目</el-tag></template></el-table-column>
                <el-table-column label="状态" width="70"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
                <el-table-column label="操作" width="90" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text type="danger" :disabled="!isSupervisor" @click="unlinkQA(row)">取消关联</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!filteredQA.length" description="暂无关联问答" />
            </el-tab-pane>

            <!-- Tab 3: Product Materials -->
            <el-tab-pane label="商品素材" name="media">
              <div class="media-toolbar">
                <el-alert
                  type="info"
                  :closable="false"
                  show-icon
                  title="一张图可以有多个场景标签"
                  description="例如尺寸图同时能回答“尺寸多大”和“是否可拆卸”，就同时打上“尺寸、可拆卸”。只有已审核且可推荐的素材，Agent 才会自动放进回复发送计划。"
                  style="flex:1;min-width:260px"
                />
                <div class="media-actions">
                  <el-input v-model="newCustomSceneTag" size="small" placeholder="新增快捷标签" style="width:120px" @keyup.enter="addCustomSceneTag" />
                  <el-button size="small" text @click="addCustomSceneTag">+</el-button>
                  <el-button size="small" :disabled="!isSupervisor" @click="refreshDingtalkMedia">刷新钉钉素材</el-button>
                  <el-upload :show-file-list="false" :http-request="handleMediaUpload" :disabled="!isSupervisor" accept="image/*,video/*" style="display:inline-block">
                    <el-button size="small" type="primary" :disabled="!isSupervisor">上传图片/视频</el-button>
                  </el-upload>
                  <el-button size="small" @click="openMediaLinkDialog">关联素材</el-button>
                  <el-button size="small" @click="$router.push('/media')">全局素材管理</el-button>
                  <el-dropdown size="small" split-button type="primary" @click="openBatchMediaDialog('add')">
                    批量标签
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item @click="openBatchMediaDialog('add')">批量添加标签</el-dropdown-item>
                        <el-dropdown-item @click="openBatchMediaDialog('remove')">批量移除标签</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                  <span style="font-size:12px;color:#909399">共 {{ productMediaAssets.length }} 条</span>
                </div>
              </div>

              <el-alert v-if="!isSupervisor" type="warning" :closable="false" show-icon title="仅主管/管理员可编辑或删除素材" description="当前账号为客服角色，素材的保存、审核、删除操作需要主管权限。" style="margin-bottom:12px" />

              <div v-loading="mediaLoading" class="media-groups">
                <template v-if="groupedMediaAssets.length">
                  <div v-for="[type, assets] in groupedMediaAssets" :key="type" class="media-group">
                    <div class="group-title">
                      <span>{{ MEDIA_PURPOSE_OPTIONS.find((o) => o.value === type)?.label || type }}</span>
                      <el-tag size="small" type="info">{{ assets.length }}</el-tag>
                    </div>
                    <el-row :gutter="12">
                      <el-col v-for="asset in assets" :key="asset.id" :xs="24" :sm="12" :md="8" :lg="6" style="margin-bottom:12px">
                        <el-card shadow="hover" class="media-card" :body-style="{ padding: '12px' }">
                          <div class="media-preview">
                            <el-tag v-if="isMediaExpired(asset)" type="danger" size="small">链接已过期</el-tag>
                            <el-image
                              v-else-if="!String(asset.asset_type || '').includes('video')"
                              :src="asset.asset_url"
                              :preview-src-list="[asset.asset_url]"
                              fit="cover"
                              class="media-card-image"
                              hide-on-click-modal
                              preview-teleported
                            />
                            <el-tag v-else type="success" size="small">视频素材</el-tag>
                          </div>
                          <div class="media-fields">
                            <el-input v-model="asset.asset_title" :disabled="!isSupervisor" size="small" placeholder="标题" />
                            <el-input v-model="asset.asset_url" :disabled="!isSupervisor" size="small" placeholder="URL" />
                            <el-select v-model="ensureAssetSourceRaw(asset).media_purpose" :disabled="!isSupervisor" size="small" placeholder="素材用途">
                              <el-option v-for="opt in MEDIA_PURPOSE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                            </el-select>
                            <div class="field-row">
                              <el-select v-model="ensureAssetSourceRaw(asset).applicable_style.scope_type" :disabled="!isSupervisor" size="small" placeholder="适用款式" style="flex:1">
                                <el-option v-for="opt in APPLICABLE_STYLE_TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                              </el-select>
                              <el-select
                                v-if="ensureAssetSourceRaw(asset).applicable_style.scope_type !== 'all'"
                                v-model="ensureAssetSourceRaw(asset).applicable_style.scope_values"
                                :disabled="!isSupervisor"
                                multiple
                                filterable
                                allow-create
                                default-first-option
                                size="small"
                                placeholder="适用值，如 SKU / 颜色 / 尺寸"
                                style="flex:1.5"
                              />
                            </div>
                            <el-input
                              v-if="ensureAssetSourceRaw(asset).applicable_style.scope_type !== 'all'"
                              v-model="ensureAssetSourceRaw(asset).applicable_style.scope_note"
                              :disabled="!isSupervisor"
                              size="small"
                              placeholder="适用备注"
                            />
                            <el-select
                              v-model="ensureAssetSourceRaw(asset).answer_scenarios"
                              :disabled="!isSupervisor"
                              multiple
                              filterable
                              allow-create
                              default-first-option
                              size="small"
                              placeholder="可回答问题"
                            >
                              <el-option v-for="opt in ANSWER_SCENARIO_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                            </el-select>
                            <div class="quick-tags">
                              <el-button v-for="opt in ANSWER_SCENARIO_OPTIONS.slice(0,6)" :key="opt.value" size="small" text :disabled="!isSupervisor" @click="addAnswerScenario(asset, opt.value)">+{{ opt.label }}</el-button>
                            </div>
                            <el-select v-model="ensureAssetSourceRaw(asset).auto_send_level" :disabled="!isSupervisor" size="small" placeholder="自动发送等级">
                              <el-option v-for="opt in AUTO_SEND_LEVEL_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                            </el-select>
                            <div class="field-row">
                              <el-select v-model="ensureAssetSourceRaw(asset).risk_level" :disabled="!isSupervisor" size="small" placeholder="风险" style="flex:1">
                                <el-option v-for="opt in RISK_LEVEL_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                              </el-select>
                              <el-select v-model="ensureAssetSourceRaw(asset).source_type" :disabled="!isSupervisor" size="small" placeholder="来源" style="flex:1">
                                <el-option v-for="opt in SOURCE_TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                              </el-select>
                            </div>
                            <div class="field-row">
                              <el-select v-model="asset.status" :disabled="!isSupervisor" size="small" placeholder="状态" style="flex:1">
                                <el-option v-for="(label, key) in STATUS_LABELS" :key="key" :label="label" :value="key" />
                              </el-select>
                              <div class="usable-switch">
                                <span>可推荐</span>
                                <el-switch v-model="asset.usable_for_agent" :disabled="!isSupervisor" />
                              </div>
                            </div>
                          </div>
                          <div class="media-card-footer">
                            <el-button size="small" type="primary" :disabled="!isSupervisor" @click="saveMedia(asset)">保存</el-button>
                            <el-button size="small" text :disabled="!isSupervisor" @click="approveMediaForAgent(asset)">审核可用</el-button>
                            <el-button size="small" text type="danger" :disabled="!isSupervisor" @click="removeMedia(asset)">删除</el-button>
                            <el-button size="small" text @click="unlinkMedia(asset)">取消关联</el-button>
                          </div>
                        </el-card>
                      </el-col>
                    </el-row>
                  </div>
                </template>
                <el-empty v-else description="暂无当前商品素材。可以先刷新钉钉素材、本地上传，或使用“关联素材”选择已有素材。" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>

    <!-- 关联已有问答 -->
    <el-dialog v-model="qaLinkDialogVisible" title="关联已有问答" width="720px" destroy-on-close>
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <el-input v-model="qaLinkSearch" placeholder="搜索问题/答案" clearable size="small" @keyup.enter="searchQALinkCandidates" />
        <el-button size="small" @click="searchQALinkCandidates">搜索</el-button>
      </div>
      <el-table :data="qaLinkCandidates" size="small" stripe v-loading="qaLinkLoading" height="360">
        <el-table-column label="客户问题" prop="question" min-width="180" show-overflow-tooltip />
        <el-table-column label="答案摘要" min-width="160"><template #default="{ row }">{{ (row.answer||'').slice(0,60) }}{{ (row.answer||'').length > 60 ? '...' : '' }}</template></el-table-column>
        <el-table-column label="意图" prop="intent" width="90" />
        <el-table-column label="风险" width="70"><template #default="{ row }"><RiskBadge :level="row.risk_level" /></template></el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }"><el-button size="small" type="primary" @click="confirmLinkQA(row)">关联</el-button></template>
        </el-table-column>
      </el-table>
      <template #footer><el-button size="small" @click="qaLinkDialogVisible = false">关闭</el-button></template>
    </el-dialog>

    <!-- 新增商品问答 -->
    <el-dialog v-model="qaCreateDialogVisible" title="新增关联问答" width="640px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="客户问题"><el-input v-model="qaCreateForm.question" type="textarea" :rows="2" placeholder="客户可能会怎么问" /></el-form-item>
        <el-form-item label="回答"><el-input v-model="qaCreateForm.answer" type="textarea" :rows="4" placeholder="建议回答内容" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="意图"><el-input v-model="qaCreateForm.intent" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="风险等级">
            <el-select v-model="qaCreateForm.risk_level" style="width:100%">
              <el-option label="低" value="low" /><el-option label="中" value="medium" />
              <el-option label="高" value="high" /><el-option label="极高" value="critical" />
            </el-select>
          </el-form-item></el-col>
        </el-row>
        <el-form-item><el-checkbox v-model="qaCreateForm.auto_reply">允许自动回复</el-checkbox></el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="qaCreateDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveQACreate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新增类目问答 -->
    <el-dialog v-model="qaCategoryDialogVisible" title="新增类目问答（关联到当前商品类目）" width="640px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon title="此类目问答会归属到当前商品所在的类目，所有同类目商品均可使用。" style="margin-bottom:12px" />
      <el-form label-position="top">
        <el-form-item label="客户问题"><el-input v-model="qaCategoryForm.question" type="textarea" :rows="2" placeholder="客户可能会怎么问" /></el-form-item>
        <el-form-item label="回答"><el-input v-model="qaCategoryForm.answer" type="textarea" :rows="4" placeholder="建议回答内容" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="意图"><el-input v-model="qaCategoryForm.intent" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="风险等级">
            <el-select v-model="qaCategoryForm.risk_level" style="width:100%">
              <el-option label="低" value="low" /><el-option label="中" value="medium" />
              <el-option label="高" value="high" /><el-option label="极高" value="critical" />
            </el-select>
          </el-form-item></el-col>
        </el-row>
        <el-form-item><el-checkbox v-model="qaCategoryForm.auto_reply">允许自动回复</el-checkbox></el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="qaCategoryDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveQACategory">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量修改 QA -->
    <el-dialog v-model="batchQADialogVisible" :title="`批量设置${batchQAField === 'risk_level' ? '风险等级' : batchQAField === 'auto_reply' ? '自动回复' : '状态'}`" width="420px" destroy-on-close>
      <p style="margin:0 0 12px;color:#606266;font-size:13px">已选择 {{ selectedQA.length }} 条问答</p>
      <el-form label-position="top">
        <el-form-item v-if="batchQAField === 'risk_level'" label="风险等级">
          <el-select v-model="batchQAValue" style="width:100%">
            <el-option label="低" value="low" /><el-option label="中" value="medium" />
            <el-option label="高" value="high" /><el-option label="极高" value="critical" />
          </el-select>
        </el-form-item>
        <el-form-item v-else-if="batchQAField === 'auto_reply'" label="是否允许自动回复">
          <el-switch v-model="batchQAValue" />
        </el-form-item>
        <el-form-item v-else label="状态">
          <el-select v-model="batchQAValue" style="width:100%">
            <el-option label="草稿" value="draft" /><el-option label="待审核" value="pending_review" />
            <el-option label="已发布" value="published" /><el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="batchQADialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" :disabled="!isSupervisor" @click="applyBatchQA">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量素材标签 -->
    <el-dialog v-model="batchMediaDialogVisible" :title="`批量${batchMediaMode === 'add' ? '添加' : '移除'}素材标签（当前商品全部素材）`" width="420px" destroy-on-close>
      <p style="margin:0 0 12px;color:#606266;font-size:13px">共 {{ productMediaAssets.length }} 条素材</p>
      <el-form label-position="top">
        <el-form-item label="标签">
          <el-select v-model="batchMediaTag" filterable allow-create default-first-option placeholder="选择或输入标签" style="width:100%">
            <el-option v-for="tag in sceneTagOptions" :key="tag.value" :label="tag.label" :value="tag.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="batchMediaDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" :disabled="!isSupervisor" @click="applyBatchMediaTag">{{ batchMediaMode === 'add' ? '添加' : '移除' }}</el-button>
      </template>
    </el-dialog>

    <!-- 关联素材 -->
    <el-dialog v-model="mediaLinkDialogVisible" title="关联素材到当前商品" width="800px" destroy-on-close>
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <el-input v-model="mediaLinkSearch" placeholder="搜索素材标题/商品名/编码" clearable size="small" @keyup.enter="searchMediaLinkCandidates" />
        <el-select v-model="mediaLinkType" placeholder="类型" clearable size="small" style="width:130px">
          <el-option v-for="(label, key) in ASSET_TYPE_LABELS" :key="key" :label="label" :value="key" />
        </el-select>
        <el-button size="small" @click="searchMediaLinkCandidates">搜索</el-button>
      </div>
      <el-table :data="mediaLinkCandidates" size="small" stripe v-loading="mediaLinkLoading" height="360">
        <el-table-column label="预览" width="80">
          <template #default="{ row }">
            <el-image v-if="!String(row.asset_type||'').includes('video')" :src="row.asset_url" fit="cover" class="media-thumb" lazy />
            <el-tag v-else type="success" size="small">视频</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" prop="asset_title" min-width="160" show-overflow-tooltip />
        <el-table-column label="商品" prop="product_name" min-width="120" show-overflow-tooltip />
        <el-table-column label="类型" width="110"><template #default="{ row }">{{ ASSET_TYPE_LABELS[row.asset_type] || row.asset_type }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="(STATUS_TAG_TYPES[row.status] as any) || 'info'" size="small">{{ STATUS_LABELS[row.status] || row.status }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }"><el-button size="small" type="primary" @click="confirmLinkMedia(row)">关联</el-button></template>
        </el-table-column>
      </el-table>
      <template #footer><el-button size="small" @click="mediaLinkDialogVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="createDialogVisible" title="新增商品" width="72%" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon title="先填写商品名称和商品编码，保存后会进入商品详情继续补全。新增商品默认是草稿，需要提交审核后再发布。" style="margin-bottom:16px" />
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
          <template v-for="group in advancedSpecGroups" :key="group.title">
            <el-col :span="24"><el-divider content-position="left">{{ group.title }}</el-divider></el-col>
            <el-col v-for="field in group.fields" :key="field.key" :span="8">
              <el-form-item :label="field.label">
                <el-input v-model="createForm.specs[field.key]" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" :placeholder="field.placeholder" />
              </el-form-item>
            </el-col>
          </template>
          <el-col :span="24"><el-divider content-position="left">售后/物流补充</el-divider></el-col>
          <el-col :span="8"><el-form-item label="质保范围"><el-input v-model="createForm.warranty.scope" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="质保例外"><el-input v-model="createForm.warranty.exclusion" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="发货说明"><el-input v-model="createForm.logistics.shipping_note" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="偏远地区说明"><el-input v-model="createForm.logistics.remote_area_note" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible=false">取消</el-button>
        <el-button type="primary" @click="saveCreate">保存并继续维护</el-button>
      </template>
    </el-dialog>

    <BatchQAManager v-model:visible="batchQAManagerVisible" :category-tree="categoryTree" @done="fetchSummary(); fetchProducts()" />
    <BatchMediaTagManager v-model:visible="batchMediaTagManagerVisible" :category-tree="categoryTree" @done="fetchSummary()" />
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
.product-card-health { display: flex; justify-content: space-between; gap: 16px; margin: 14px 0; padding: 12px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafcff; }
.missing-chips { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; max-width: 55%; }
.media-thumb { width: 56px; height: 56px; border-radius: 6px; border: 1px solid #e4e7ed; background: #f5f7fa; }

/* Detail header */
.detail-header { display: flex; justify-content: space-between; align-items: center; background: #fff; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.detail-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.meta-item { font-size: 13px; color: #606266; }
.detail-health { text-align: center; }
.dh-score { font-size: 22px; font-weight: 800; line-height: 1; }
.dh-label { font-size: 11px; color: #909399; }

/* Media tab */
.media-toolbar { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.media-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.media-groups { min-height: 200px; }
.media-group { margin-bottom: 20px; }
.group-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #303133; margin-bottom: 10px; }
.media-card { transition: all .2s; }
.media-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.1); }
.media-preview { width: 100%; height: 140px; border-radius: 6px; background: #f5f7fa; border: 1px solid #e4e7ed; display: flex; align-items: center; justify-content: center; overflow: hidden; margin-bottom: 10px; }
.media-card-image { width: 100%; height: 100%; object-fit: cover; }
.media-fields { display: flex; flex-direction: column; gap: 8px; }
.field-row { display: flex; gap: 8px; }
.usable-switch { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #606266; white-space: nowrap; }
.quick-tags { display: flex; flex-wrap: wrap; gap: 2px; }
.media-card-footer { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
</style>
