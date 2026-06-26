<script setup lang="ts">
import { ref, reactive, onMounted, computed, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search,
  Picture,
  Delete,
  Edit,
  ArrowRight,
  DataLine,
  Document,
  WarningFilled,
  Collection,
  Calendar,
  User,
  Shop,
  ChatLineRound,
  Flag,
  CircleCheck,
  Plus,
} from '@element-plus/icons-vue'
import RichEditor from '../components/RichEditor.vue'
import {
  createTrainingSample,
  getTrainingSamples,
  getTrainingSample,
  updateTrainingSample,
  deleteTrainingSample,
  deleteTrainingSampleAttachment,
  getTrainingSampleAttachmentUrl,
  uploadTrainingSampleMedia,
  type TrainingSample,
  type TrainingSampleAttachment,
} from '../api/trainingSample'

const today = new Date().toISOString().split('T')[0]
const route = useRoute()

const form = reactive({
  id: null as number | null,
  collected_at: today,
  csr_name: '',
  shop_platform: '',
  customer_quote: '',
  full_context: '',
  product_title: '',
  sku: '',
  order_no: '',
  question_type: '',
  difficulty_reason: '',
  csr_actual_reply: '',
  correct_answer: '',
  need_knowledge_base: false,
  target_knowledge_base: '',
  need_media: false,
  media_links: [] as string[],
  risk_level: '中',
  auto_reply_type: '需人工确认',
  review_status: '待处理',
  owner: '',
  notes: '',
})

const list = ref<TrainingSample[]>([])
const total = ref(0)
const loading = ref(false)
const submitting = ref(false)
const drawerVisible = ref(false)
const detail = ref<TrainingSample | null>(null)
const activeTab = ref('form')
const activeSection = ref('basic')

const filters = ref({
  review_status: '',
  question_type: '',
  keyword: '',
  page: 1,
  page_size: 10,
})
const listGroupFilter = ref<'all' | 'pending' | 'reviewed' | 'evalset'>('all')

const shopPlatforms = ['天猫', '淘宝', '拼多多', '抖音', '京东', '快手', '小红书', '其他']
const questionTypes = ['材质安全', '安装', '尺寸', '配件', '物流', '售后', '活动', '质检', '年龄适配', '其他']
const difficultyReasons = ['知识库没有', '图片看不清', '商品不确定', '政策不清', '需要质检资料', '需要货品确认', '其他']
const knowledgeTargets = ['RAG知识', '商品属性', '安装说明', '素材图片', '售后规则', '物流规则']
const riskLevels = ['低', '中', '高']
const autoReplyTypes = ['可自动', '需人工确认', '禁止自动']
const reviewStatuses = ['待处理', '已确认', '评测集', '已入库', '已上线']

const sections = [
  { id: 'basic', label: '基础信息', icon: Calendar },
  { id: 'dialog', label: '对话内容', icon: ChatLineRound },
  { id: 'product', label: '商品与订单', icon: Shop },
  { id: 'reply', label: '难点与回复', icon: Edit },
  { id: 'media', label: '配图/视频', icon: Picture },
  { id: 'review', label: '风险与审核', icon: Flag },
]

const stats = computed(() => {
  const todayStr = new Date().toISOString().split('T')[0]
  return {
    total: total.value,
    today: list.value.filter((i) => (i.collected_at || i.created_at || '').startsWith(todayStr)).length,
    pending: list.value.filter((i) => i.review_status === '待处理').length,
    evalSet: list.value.filter((i) => i.review_status === '评测集').length,
    needKb: list.value.filter((i) => i.need_knowledge_base).length,
  }
})

const listGroups = computed(() => {
  let source = list.value
  if (listGroupFilter.value === 'pending') {
    source = list.value.filter((i) => i.review_status === '待处理')
  } else if (listGroupFilter.value === 'reviewed') {
    source = list.value.filter((i) => i.review_status === '已确认')
  } else if (listGroupFilter.value === 'evalset') {
    source = list.value.filter((i) => i.review_status === '评测集')
  }
  const pending = source.filter((i) => i.review_status === '待处理')
  const confirmed = source.filter((i) => i.review_status === '已确认')
  const evalSet = source.filter((i) => i.review_status === '评测集')
  const groups = []
  if (pending.length) {
    groups.push({ title: '未审核', key: 'pending', items: pending, count: pending.length })
  }
  if (confirmed.length) {
    groups.push({ title: '已审核', key: 'confirmed', items: confirmed, count: confirmed.length })
  }
  if (evalSet.length) {
    groups.push({ title: '评测集', key: 'evalset', items: evalSet, count: evalSet.length })
  }
  return groups
})

const isEditing = computed(() => !!form.id)
const suggestedKnowledgeTarget = computed(() => {
  if (form.need_media) return '素材标签/图片视频'
  if (['材质安全', '安装', '尺寸', '配件', '质检', '年龄适配'].includes(form.question_type)) return '商品卡片/商品资料'
  if (form.question_type === '物流') return '物流规则'
  if (form.question_type === '售后') return '售后规则'
  if (form.question_type === '活动') return '活动规则'
  return '回复模板/话术'
})
const knowledgeTargetHint = computed(() => {
  const target = form.target_knowledge_base || suggestedKnowledgeTarget.value
  if (target === '商品卡片/商品资料') return '建议补到对应商品详情页的基础资料：可拆卸、尺寸、安装、材质、安全、质检、配件等事实都放这里。'
  if (target === '素材标签/图片视频') return '建议到商品详情的“关联素材”里打标签并审核可推荐：尺寸、可拆卸、安装、配件、证书等。'
  if (target === '回复模板/话术') return '适合沉淀通用表达方式，不承载具体商品事实。'
  return '适合沉淀平台政策、店铺规则或外部查询规则。'
})
watch(
  () => [form.need_knowledge_base, form.question_type, form.need_media],
  () => {
    if (form.need_knowledge_base && !form.target_knowledge_base) {
      form.target_knowledge_base = suggestedKnowledgeTarget.value
    }
  },
)
const customerQuoteTouched = ref(false)

function htmlToPlainText(html: string) {
  if (!html) return ''
  const div = document.createElement('div')
  div.innerHTML = html
  div.querySelectorAll('br').forEach((node) => node.replaceWith('\n'))
  div.querySelectorAll('p, div, li').forEach((node) => node.append('\n'))
  return (div.textContent || div.innerText || '').replace(/\u00a0/g, ' ').trim()
}

function extractFirstCustomerQuestion(html: string) {
  if (!html) return ''
  const hasImage = /<img\b/i.test(html)
  const text = htmlToPlainText(html)
  const lines = text
    .split(/\r?\n+/)
    .map((line) => line.replace(/^(客户|买家|用户|顾客|客服|商家|我|对方)[:：]\s*/u, '').trim())
    .filter(Boolean)
  const question = lines.find((line) => /[？?]|吗|呢|怎么|如何|能不能|是不是|有没有|会不会|为什么|多少|哪里|哪个/u.test(line))
  const firstText = question || lines[0] || ''
  if (firstText) {
    return hasImage ? `${firstText} [图片]`.slice(0, 300) : firstText.slice(0, 300)
  }
  return hasImage ? '[图片消息]' : ''
}

function extractLinks(html: string) {
  const found = new Set<string>()
  const div = document.createElement('div')
  div.innerHTML = html || ''
  div.querySelectorAll('a[href]').forEach((node) => {
    const href = (node as HTMLAnchorElement).href
    if (href && /^https?:\/\//i.test(href)) found.add(href)
  })
  const plain = htmlToPlainText(html)
  for (const match of plain.matchAll(/https?:\/\/[^\s<>"'，。；、\u4e00-\u9fff]+/g)) {
    found.add(match[0].replace(/[),.;!?，。；！？、]+$/u, ''))
  }
  return Array.from(found)
}

function updateFullContext(value: string) {
  form.full_context = value
  if (!customerQuoteTouched.value || !form.customer_quote.trim()) {
    const quote = extractFirstCustomerQuestion(value)
    if (quote) form.customer_quote = quote
  }
  const links = extractLinks(value)
  if (links.length) {
    const merged = new Set(form.media_links)
    links.forEach((link) => merged.add(link))
    form.media_links = Array.from(merged)
    form.need_media = true
  }
}

function resetForm() {
  customerQuoteTouched.value = false
  Object.assign(form, {
    id: null,
    collected_at: today,
    csr_name: '',
    shop_platform: '',
    customer_quote: '',
    full_context: '',
    product_title: '',
    sku: '',
    order_no: '',
    question_type: '',
    difficulty_reason: '',
    csr_actual_reply: '',
    correct_answer: '',
    need_knowledge_base: false,
    target_knowledge_base: '',
    need_media: false,
    media_links: [],
    risk_level: '中',
    auto_reply_type: '需人工确认',
    review_status: '待处理',
    owner: '',
    notes: '',
  })
}

async function submitForm() {
  if (!form.customer_quote.trim()) {
    ElMessage.warning('请填写客户原话（系统会从完整聊天中自动提取，也可手动输入）')
    return
  }
  if (!form.question_type) {
    ElMessage.warning('请选择问题类型')
    return
  }

  submitting.value = true
  try {
    const payload = {
      collected_at: form.collected_at,
      csr_name: form.csr_name,
      shop_platform: form.shop_platform,
      customer_quote: form.customer_quote,
      full_context: form.full_context,
      product_title: form.product_title,
      sku: form.sku,
      order_no: form.order_no,
      question_type: form.question_type,
      difficulty_reason: form.difficulty_reason,
      csr_actual_reply: form.csr_actual_reply,
      correct_answer: form.correct_answer,
      need_knowledge_base: form.need_knowledge_base,
      target_knowledge_base: form.target_knowledge_base,
      need_media: form.need_media,
      media_links: form.media_links,
      risk_level: form.risk_level,
      auto_reply_type: form.auto_reply_type,
      review_status: form.review_status,
      owner: form.owner,
      notes: form.notes,
    }

    if (isEditing.value) {
      await updateTrainingSample(form.id!, payload)
      ElMessage.success('更新成功')
    } else {
      await createTrainingSample(payload)
      ElMessage.success('保存成功')
      resetForm()
      activeTab.value = 'list'
    }
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function fetchList() {
  loading.value = true
  try {
    const offset = (filters.value.page - 1) * filters.value.page_size
    const { data } = await getTrainingSamples({
      review_status: filters.value.review_status,
      question_type: filters.value.question_type,
      keyword: filters.value.keyword,
      limit: filters.value.page_size,
      offset,
    })
    list.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    console.error(e)
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  filters.value.page = 1
  fetchList()
}

function handleReset() {
  filters.value = {
    review_status: '',
    question_type: '',
    keyword: '',
    page: 1,
    page_size: 10,
  }
  fetchList()
}

async function editSample(item: TrainingSample) {
  customerQuoteTouched.value = true
  activeTab.value = 'form'
  Object.assign(form, {
    id: item.id,
    collected_at: item.collected_at ? item.collected_at.split('T')[0] : today,
    csr_name: item.csr_name,
    shop_platform: item.shop_platform,
    customer_quote: item.customer_quote,
    full_context: item.full_context,
    product_title: item.product_title,
    sku: item.sku,
    order_no: item.order_no,
    question_type: item.question_type,
    difficulty_reason: item.difficulty_reason,
    csr_actual_reply: item.csr_actual_reply,
    correct_answer: item.correct_answer,
    need_knowledge_base: item.need_knowledge_base,
    target_knowledge_base: item.target_knowledge_base,
    need_media: item.need_media,
    media_links: item.media_links || [],
    risk_level: item.risk_level,
    auto_reply_type: item.auto_reply_type,
    review_status: item.review_status,
    owner: item.owner,
    notes: item.notes,
  })
  nextTick(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  })
}

async function deleteSample(item: TrainingSample) {
  try {
    await ElMessageBox.confirm(
      `确定删除样本 #${item.id} 吗？删除后不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await deleteTrainingSample(item.id)
    ElMessage.success('删除成功')
    fetchList()
    if (form.id === item.id) {
      resetForm()
    }
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

async function viewDetail(item: TrainingSample) {
  drawerVisible.value = true
  try {
    const { data } = await getTrainingSample(item.id)
    detail.value = data
  } catch {
    ElMessage.error('加载详情失败')
  }
}

function removeMediaLink(index: number) {
  form.media_links.splice(index, 1)
}

const mediaUploading = ref(false)

async function uploadMediaFiles(files: FileList | null) {
  if (!files || !files.length) return
  mediaUploading.value = true
  try {
    for (const file of Array.from(files)) {
      const { data } = await uploadTrainingSampleMedia(file)
      if (data?.url) {
        form.media_links.push(data.url)
      }
    }
    if (form.media_links.length) {
      form.need_media = true
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '媒体上传失败')
  } finally {
    mediaUploading.value = false
  }
}

async function onMediaPaste(event: ClipboardEvent) {
  const clipboard = event.clipboardData
  if (!clipboard) return
  const files = Array.from(clipboard.items)
    .filter((item) => item.kind === 'file' && (/^image\//.test(item.type) || /^video\//.test(item.type)))
    .map((item) => item.getAsFile())
    .filter((file): file is File => !!file)
  if (!files.length) return
  event.preventDefault()
  await uploadMediaFiles(files as unknown as FileList)
}

function onMediaDrop(event: DragEvent) {
  event.preventDefault()
  uploadMediaFiles(event.dataTransfer?.files || null)
}

function switchTab(tab: string) {
  activeTab.value = tab
}

function scrollToSection(id: string) {
  const el = document.getElementById('section-' + id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function scrollToList() {
  activeTab.value = 'list'
}

let sectionObserver: IntersectionObserver | null = null
function setupSectionObserver() {
  sectionObserver?.disconnect()
  sectionObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          activeSection.value = entry.target.id.replace('section-', '')
        }
      })
    },
    { rootMargin: '-10% 0px -75% 0px', threshold: 0 }
  )
  sections.forEach((s) => {
    const el = document.getElementById('section-' + s.id)
    if (el) sectionObserver!.observe(el)
  })
}

watch(activeTab, (tab) => {
  if (tab === 'form') {
    nextTick(setupSectionObserver)
  }
})

function formatDate(d: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function stripHtml(html: string) {
  if (!html) return ''
  return html.replace(/<[^>]+>/g, '').slice(0, 120)
}

function isImageUrl(url: string) {
  return /\.(png|jpg|jpeg|webp|gif)(\?.*)?$/i.test(url || '')
}

function isVideoUrl(url: string) {
  return /\.(mp4|webm|mov)(\?.*)?$/i.test(url || '')
}

function isMediaPreviewable(url: string) {
  return isImageUrl(url) || isVideoUrl(url)
}

function renderEmpty(html: string) {
  return html || '<span class="empty">无内容</span>'
}

onMounted(async () => {
  await fetchList()
  nextTick(setupSectionObserver)
  const queryId = route.query.id
  if (queryId) {
    const id = Number(queryId)
    if (!isNaN(id)) {
      try {
        const { data } = await getTrainingSample(id)
        editSample(data)
      } catch {
        ElMessage.error('要编辑的样本不存在')
      }
    }
  }
})
</script>

<template>
  <div class="ts-page page-container">
    <div class="ts-inner">
      <!-- 页面标题 -->
      <div class="ts-header">
        <div class="ts-title-wrap">
          <h2>训练样本收集</h2>
          <p class="subtitle">录入最新客服对话，沉淀成客服系统的训练数据。支持图文混排、一键提取。</p>
        </div>
        <a class="header-link" href="/ask/real-test" title="返回客服工作台">
          ← 返回工作台
        </a>
      </div>

      <!-- 统计指标 -->
      <div class="stats-bar">
        <div class="stat-card">
          <div class="stat-icon total"><el-icon><Document /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.total }}</div>
            <div class="stat-label">累计样本</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon today"><el-icon><Calendar /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.today }}</div>
            <div class="stat-label">今日新增</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon pending"><el-icon><WarningFilled /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.pending }}</div>
            <div class="stat-label">待处理</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon kb"><el-icon><DataLine /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.evalSet }}</div>
            <div class="stat-label">评测集</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon kb"><el-icon><Collection /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.needKb }}</div>
            <div class="stat-label">需补知识库</div>
          </div>
        </div>
      </div>

      <!-- 标签切换 -->
      <div class="ts-tabs">
        <div
          class="tab-item"
          :class="{ active: activeTab === 'form' }"
          @click="switchTab('form')"
        >
          <el-icon><Plus /></el-icon>
          <span>新增样本</span>
        </div>
        <div
          class="tab-item"
          :class="{ active: activeTab === 'list' }"
          @click="switchTab('list')"
        >
          <el-icon><DataLine /></el-icon>
          <span>样本库</span>
          <span class="tab-count">{{ total }}</span>
        </div>
      </div>

      <!-- 录入面板 -->
      <div v-show="activeTab === 'form'" class="tab-panel form-panel">
        <div class="form-layout">
          <nav class="section-nav">
            <div
              v-for="s in sections"
              :key="s.id"
              class="nav-item"
              :class="{ active: activeSection === s.id }"
              @click="scrollToSection(s.id)"
            >
              <el-icon><component :is="s.icon" /></el-icon>
              <span>{{ s.label }}</span>
            </div>
          </nav>

          <div class="form-card">
            <div class="card-head">
              <h3>{{ isEditing ? '编辑样本 #' + form.id : '新增训练样本' }}</h3>
              <el-button v-if="isEditing" text @click="resetForm">取消编辑</el-button>
            </div>

            <el-form label-position="top" class="ts-form">
              <div id="section-basic" class="section-title">基础信息</div>
              <div class="form-grid grid-4">
                <el-form-item label="收集日期">
                  <el-date-picker v-model="form.collected_at" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
                </el-form-item>
                <el-form-item label="客服姓名">
                  <el-input v-model="form.csr_name" placeholder="谁遇到的" />
                </el-form-item>
                <el-form-item label="店铺/平台">
                  <el-select v-model="form.shop_platform" placeholder="选择平台" clearable style="width: 100%">
                    <el-option v-for="p in shopPlatforms" :key="p" :label="p" :value="p" />
                  </el-select>
                </el-form-item>
                <el-form-item label="问题类型">
                  <el-select v-model="form.question_type" placeholder="选择类型" clearable style="width: 100%">
                    <el-option v-for="t in questionTypes" :key="t" :label="t" :value="t" />
                  </el-select>
                </el-form-item>
              </div>

              <div id="section-dialog" class="section-title">对话内容</div>
              <el-form-item label="一键粘贴完整聊天">
                <RichEditor
                  :model-value="form.full_context"
                  placeholder="把千牛/钉钉/微信里的整段聊天、商品链接、图片截图直接粘到这里；系统会自动提取客户原话和链接"
                  :min-height="260"
                  :max-height="720"
                  :show-toolbar="false"
                  tip="支持一次性粘贴文字、链接、截图和商品图；图片提交后会自动转存为附件，链接会自动收集到下方素材链接。"
                  @update:model-value="updateFullContext"
                />
              </el-form-item>
              <el-form-item label="客户原话（自动提取，可手动改）">
                <el-input
                  v-model="form.customer_quote"
                  type="textarea"
                  :rows="3"
                  placeholder="系统会从上面的完整聊天里自动提取，也可以手动改成客户最关键的问题"
                  @input="customerQuoteTouched = true"
                />
              </el-form-item>

              <div id="section-product" class="section-title">商品与订单</div>
              <div class="form-grid grid-3">
                <el-form-item label="商品标题">
                  <el-input v-model="form.product_title" placeholder="页面长标题" />
                </el-form-item>
                <el-form-item label="商品编码 / SKU">
                  <el-input v-model="form.sku" placeholder="最好必填" />
                </el-form-item>
                <el-form-item label="订单号">
                  <el-input v-model="form.order_no" placeholder="售后/物流/配件问题必填" />
                </el-form-item>
              </div>

              <div id="section-reply" class="section-title">难点与回复</div>
              <div class="form-grid grid-2">
                <el-form-item label="为什么难回答">
                  <el-select v-model="form.difficulty_reason" placeholder="选择原因" clearable style="width: 100%">
                    <el-option v-for="r in difficultyReasons" :key="r" :label="r" :value="r" />
                  </el-select>
                </el-form-item>
                <el-form-item label="是否需要补知识库">
                  <div class="switch-row">
                    <el-switch v-model="form.need_knowledge_base" />
                    <el-select
                      v-if="form.need_knowledge_base"
                      v-model="form.target_knowledge_base"
                      placeholder="应补到哪里"
                      clearable
                      style="flex: 1; margin-left: 12px"
                    >
                      <el-option v-for="k in knowledgeTargets" :key="k" :label="k" :value="k" />
                    </el-select>
                  </div>
                  <el-alert
                    v-if="form.need_knowledge_base"
                    :title="knowledgeTargetHint"
                    type="info"
                    :closable="false"
                    show-icon
                    class="kb-target-hint"
                  />
                </el-form-item>
              </div>
              <el-form-item label="客服实际怎么回复">
                <RichEditor v-model="form.csr_actual_reply" placeholder="当时发给客户的话" />
              </el-form-item>
              <el-form-item label="标准答案批注（可选，审核时填写）">
                <el-input
                  v-model="form.correct_answer"
                  type="textarea"
                  :rows="3"
                  placeholder="主管/货品/售后确认后的标准答案或批注；如暂不确定可留空"
                />
              </el-form-item>

              <div id="section-media" class="section-title">配图/视频</div>
              <el-form-item label="是否需要配图/视频">
                <el-switch v-model="form.need_media" />
              </el-form-item>
              <el-form-item v-if="form.need_media" label="配图/视频">
                <div class="media-gallery">
                  <div
                    class="media-paste-zone"
                    tabindex="0"
                    :class="{ uploading: mediaUploading }"
                    @paste="onMediaPaste"
                    @drop="onMediaDrop"
                    @dragover.prevent
                  >
                    <el-icon :size="32"><Picture /></el-icon>
                    <p class="paste-title">按 Ctrl + V 粘贴图片/视频</p>
                    <p class="paste-sub">或直接把文件拖到这里</p>
                    <p class="paste-formats">支持 PNG / JPG / GIF / WEBP / MP4 / MOV / WEBM，单个最大 50MB</p>
                  </div>

                  <div v-if="form.media_links.length" class="media-items">
                    <div v-for="(link, idx) in form.media_links" :key="idx" class="media-card">
                      <template v-if="isMediaPreviewable(link)">
                        <img v-if="isImageUrl(link)" :src="link" class="media-card-preview" />
                        <video v-else :src="link" class="media-card-preview" controls />
                      </template>
                      <div v-else class="media-card-unknown">{{ link }}</div>
                      <el-button class="media-card-delete" type="danger" link :icon="Delete" @click="removeMediaLink(idx)">
                        删除
                      </el-button>
                    </div>
                  </div>
                </div>
              </el-form-item>

              <div id="section-review" class="section-title">风险与审核</div>
              <div class="form-grid grid-4">
                <el-form-item label="风险等级">
                  <el-select v-model="form.risk_level" style="width: 100%">
                    <el-option v-for="r in riskLevels" :key="r" :label="r" :value="r" />
                  </el-select>
                </el-form-item>
                <el-form-item label="是否可自动回复">
                  <el-select v-model="form.auto_reply_type" style="width: 100%">
                    <el-option v-for="t in autoReplyTypes" :key="t" :label="t" :value="t" />
                  </el-select>
                </el-form-item>
                <el-form-item label="审核状态">
                  <el-select v-model="form.review_status" style="width: 100%">
                    <el-option v-for="s in reviewStatuses" :key="s" :label="s" :value="s" />
                  </el-select>
                </el-form-item>
                <el-form-item label="负责人">
                  <el-input v-model="form.owner" placeholder="谁负责补资料" />
                </el-form-item>
              </div>

              <el-form-item label="备注">
                <el-input v-model="form.notes" type="textarea" :rows="2" placeholder="其他说明" />
              </el-form-item>

              <div class="form-actions">
                <el-button type="primary" size="large" :loading="submitting" @click="submitForm">
                  {{ isEditing ? '保存修改' : '保存样本' }}
                </el-button>
                <el-button size="large" @click="resetForm">重置</el-button>
              </div>
            </el-form>
          </div>
        </div>
      </div>

      <!-- 样本库面板 -->
      <div v-show="activeTab === 'list'" class="tab-panel list-panel">
        <div class="list-header">
          <h3>已收集样本</h3>
          <div class="filter-row">
            <el-select v-model="filters.review_status" placeholder="审核状态" clearable style="width: 140px" @change="handleSearch">
              <el-option v-for="s in reviewStatuses" :key="s" :label="s" :value="s" />
            </el-select>
            <el-select v-model="filters.question_type" placeholder="问题类型" clearable style="width: 140px" @change="handleSearch">
              <el-option v-for="t in questionTypes" :key="t" :label="t" :value="t" />
            </el-select>
            <el-input v-model="filters.keyword" placeholder="搜索客户原话 / SKU / 订单号" clearable style="width: 240px" @keyup.enter="handleSearch">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-button type="primary" @click="handleSearch">查询</el-button>
            <el-button @click="handleReset">重置</el-button>
          </div>
        </div>

        <div class="list-group-filter">
          <el-radio-group v-model="listGroupFilter" size="small" fill="#1b61c9">
            <el-radio-button label="all">全部 ({{ total }})</el-radio-button>
            <el-radio-button label="pending">未审核 ({{ list.filter(i => i.review_status === '待处理').length }})</el-radio-button>
            <el-radio-button label="reviewed">已审核 ({{ list.filter(i => i.review_status === '已确认').length }})</el-radio-button>
            <el-radio-button label="evalset">评测集 ({{ list.filter(i => i.review_status === '评测集').length }})</el-radio-button>
          </el-radio-group>
        </div>

        <div v-loading="loading" class="sample-list">
          <div v-for="group in listGroups" :key="group.key" class="sample-group">
            <div class="group-header">
              <span class="group-title">{{ group.title }}</span>
              <span class="group-count">{{ group.count }}</span>
            </div>
            <div
              v-for="item in group.items"
              :key="item.id"
              class="sample-row"
              :class="'risk-border-' + item.risk_level"
              @click="viewDetail(item)"
            >
              <div class="row-main">
                <div class="row-top">
                  <span class="row-id">#{{ item.id }}</span>
                  <el-tag size="small" :type="item.review_status === '待处理' ? 'warning' : item.review_status === '已上线' ? 'success' : 'primary'">
                    {{ item.review_status }}
                  </el-tag>
                  <el-tag size="small" type="info">{{ item.question_type || '未分类' }}</el-tag>
                  <span class="row-date">{{ formatDate(item.created_at) }}</span>
                </div>
                <div class="row-quote" v-html="renderEmpty(item.customer_quote)"></div>
                <div class="row-meta">
                  <span v-if="item.shop_platform"><el-icon><Shop /></el-icon> {{ item.shop_platform }}</span>
                  <span v-if="item.sku">SKU {{ item.sku }}</span>
                  <span v-if="item.order_no">订单 {{ item.order_no }}</span>
                  <span v-if="item.csr_name"><el-icon><User /></el-icon> {{ item.csr_name }}</span>
                </div>
              </div>
              <div class="row-side">
                <div class="row-risk-badge" :class="'risk-' + item.risk_level">{{ item.risk_level }}风险</div>
                <div class="row-auto">{{ item.auto_reply_type }}</div>
                <div class="row-actions" @click.stop>
                  <el-button link type="primary" :icon="Edit" @click="editSample(item)">编辑</el-button>
                  <el-button link type="danger" :icon="Delete" @click="deleteSample(item)">删除</el-button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="!list.length && !loading" class="empty-state">
            <el-icon :size="56"><Document /></el-icon>
            <p class="empty-title">还没有样本</p>
            <p class="empty-sub">录入第一条客服对话，开始沉淀训练数据</p>
            <el-button type="primary" @click="switchTab('form')">去录入</el-button>
          </div>
        </div>

        <div v-if="list.length" class="pagination-bar">
          <el-pagination
            v-model:current-page="filters.page"
            v-model:page-size="filters.page_size"
            :total="total"
            layout="total, sizes, prev, pager, next"
            :page-sizes="[10, 20, 50]"
            @change="fetchList"
          />
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" title="样本详情" size="720px" destroy-on-close>
      <div v-if="detail" class="detail-body">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="收集日期">{{ detail.collected_at ? detail.collected_at.split('T')[0] : '-' }}</el-descriptions-item>
          <el-descriptions-item label="客服">{{ detail.csr_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ detail.shop_platform || '-' }}</el-descriptions-item>
          <el-descriptions-item label="问题类型">{{ detail.question_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="风险等级">{{ detail.risk_level }}</el-descriptions-item>
          <el-descriptions-item label="自动回复">{{ detail.auto_reply_type }}</el-descriptions-item>
          <el-descriptions-item label="审核状态">{{ detail.review_status }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ detail.owner || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="detail-section">
          <h4>客户原话</h4>
          <div class="rich-preview" v-html="renderEmpty(detail.customer_quote)"></div>
        </div>
        <div class="detail-section">
          <h4>完整上下文</h4>
          <div class="rich-preview" v-html="renderEmpty(detail.full_context)"></div>
        </div>
        <div class="detail-section">
          <h4>客服实际回复</h4>
          <div class="rich-preview" v-html="renderEmpty(detail.csr_actual_reply)"></div>
        </div>
        <div class="detail-section">
          <h4>标准答案批注</h4>
          <div class="rich-preview" v-html="renderEmpty(detail.correct_answer)"></div>
        </div>
        <div v-if="detail.eval_contract && Object.keys(detail.eval_contract).length" class="detail-section">
          <h4>评测契约</h4>
          <div class="contract-preview">
            <p><strong>契约版本：</strong>{{ detail.eval_contract.schema_version || detail.eval_contract.source || '-' }}</p>
            <p><strong>预期类型：</strong>{{ detail.eval_contract.expected_question_type || '-' }}</p>
            <p><strong>可自动评分：</strong>{{ detail.eval_contract.can_auto_score ? '是' : '否' }}</p>
            <p><strong>需要图片说明：</strong>{{ detail.eval_contract.needs_image_description ? '是' : '否' }}</p>
            <p><strong>完整上下文：</strong>{{ detail.eval_contract.conversation_context_text ? '已保留' : '-' }}</p>
            <p><strong>媒体引用：</strong>{{ (detail.eval_contract.media_references || []).length }} 个</p>
            <div v-if="(detail.eval_contract.expected_agent_turns || []).length" class="expected-turns">
              <div
                v-for="(turn, idx) in detail.eval_contract.expected_agent_turns"
                :key="idx"
                class="expected-turn"
              >
                <p><strong>客户说：</strong>{{ turn.customer_said || '-' }}</p>
                <p><strong>应该回答：</strong>{{ turn.expected_reply || '-' }}</p>
                <p><strong>必须做到：</strong>{{ (turn.must_do || []).join('；') || '-' }}</p>
                <p><strong>不能做：</strong>{{ (turn.must_not_do || []).join('；') || '-' }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
// Airtable 设计系统 — 白色画布 + 深海军蓝文字 + Airtable 蓝强调色
// 参考：.tools/open-design/design-systems/airtable
.ts-page {
  --at-bg: #ffffff;
  --at-surface: #f8fafc;
  --at-page: #f4f6f8;
  --at-fg: #181d26;
  --at-fg-2: #333333;
  --at-muted: rgba(4, 14, 32, 0.69);
  --at-meta: rgba(4, 14, 32, 0.45);
  --at-border: #e0e2e6;
  --at-border-strong: #d1d5db;
  --at-accent: #1b61c9;
  --at-accent-hover: #254fad;
  --at-accent-subtle: #eef4ff;
  --at-success: #006400;
  --at-warn: #9b6829;
  --at-danger: #dc2626;
  --at-shadow: rgba(0, 0, 0, 0.32) 0px 0px 1px, rgba(0, 0, 0, 0.08) 0px 0px 2px,
    rgba(45, 127, 249, 0.28) 0px 1px 3px, rgba(0, 0, 0, 0.06) 0px 0px 0px 0.5px inset;
  --at-shadow-hover: rgba(0, 0, 0, 0.32) 0px 0px 1px, rgba(0, 0, 0, 0.12) 0px 0px 4px,
    rgba(45, 127, 249, 0.32) 0px 2px 6px, rgba(0, 0, 0, 0.06) 0px 0px 0px 0.5px inset;
  --at-radius-sm: 8px;
  --at-radius-md: 12px;
  --at-radius-lg: 16px;
  --at-radius-xl: 20px;
  --at-space-1: 4px;
  --at-space-2: 8px;
  --at-space-3: 12px;
  --at-space-4: 16px;
  --at-space-5: 20px;
  --at-space-6: 24px;
  --at-space-8: 32px;

  // 覆盖项目全局令牌，使本页 Element Plus 组件也融入 Airtable 风格
  --kb-accent: var(--at-accent);
  --kb-accent-hover: var(--at-accent-hover);
  --kb-accent-subtle: var(--at-accent-subtle);
  --kb-bg-card: var(--at-bg);
  --kb-bg-hover: var(--at-surface);
  --kb-text-primary: var(--at-fg);
  --kb-text-secondary: var(--at-fg-2);
  --kb-text-tertiary: var(--at-muted);
  --kb-border: var(--at-border);
  --kb-border-strong: var(--at-border-strong);
  --kb-success-text: var(--at-success);
  --kb-warning-text: var(--at-warn);
  --kb-danger-text: var(--at-danger);
  --kb-radius-sm: var(--at-radius-sm);
  --kb-radius-md: var(--at-radius-md);
  --kb-radius-lg: var(--at-radius-lg);
  --kb-shadow-card: var(--at-shadow);
  --kb-shadow-card-hover: var(--at-shadow-hover);

  background: var(--at-page);
  min-height: 100vh;
  color: var(--at-fg);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
}

.ts-inner {
  max-width: 1180px;
  margin: 0 auto;
}

// 页面标题
.ts-header {
  margin-bottom: var(--at-space-6);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--at-space-4);

  .ts-title-wrap {
    max-width: 640px;
  }

  h2 {
    margin: 0 0 var(--at-space-2);
    font-size: 34px;
    font-weight: 700;
    color: var(--at-fg);
    letter-spacing: -0.03em;
    line-height: 1.1;
  }

  .subtitle {
    margin: 0;
    color: var(--at-muted);
    font-size: 15px;
    line-height: 1.5;
  }

  .header-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 8px 14px;
    border-radius: var(--at-radius-md);
    color: var(--at-muted);
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    background: var(--at-bg);
    border: 1px solid var(--at-border);
    box-shadow: var(--at-shadow);
    transition: all 0.15s ease;

    &:hover {
      border-color: var(--at-border-strong);
      color: var(--at-fg);
      box-shadow: var(--at-shadow-hover);
    }
  }
}

// 统计指标
.stats-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--at-space-4);
  margin-bottom: var(--at-space-6);

  @media (max-width: 900px) {
    grid-template-columns: repeat(2, 1fr);
  }
  @media (max-width: 520px) {
    grid-template-columns: 1fr;
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: var(--at-space-4);
  padding: var(--at-space-4);
  background: var(--at-bg);
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-lg);
  box-shadow: var(--at-shadow);
  transition: box-shadow 0.2s ease, transform 0.15s ease;

  &:hover {
    box-shadow: var(--at-shadow-hover);
    transform: translateY(-1px);
  }

  .stat-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border-radius: var(--at-radius-md);
    color: #fff;

    &.total { background: linear-gradient(135deg, #1b61c9, #4f8df5); }
    &.today { background: linear-gradient(135deg, #0f766e, #14b8a6); }
    &.pending { background: linear-gradient(135deg, #c2410c, #f97316); }
    &.kb { background: linear-gradient(135deg, #7c3aed, #a78bfa); }
  }

  .stat-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .stat-value {
    font-size: 26px;
    font-weight: 700;
    color: var(--at-fg);
    line-height: 1;
    letter-spacing: -0.02em;
  }

  .stat-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--at-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
}

// 标签切换
.ts-tabs {
  display: flex;
  gap: var(--at-space-1);
  margin-bottom: var(--at-space-4);
  padding: 4px;
  background: var(--at-surface);
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-md);
  width: fit-content;

  .tab-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border-radius: var(--at-radius-sm);
    color: var(--at-muted);
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
    user-select: none;

    &:hover {
      color: var(--at-fg);
      background: rgba(255, 255, 255, 0.6);
    }

    &.active {
      color: var(--at-fg);
      background: var(--at-bg);
      box-shadow: var(--at-shadow);
    }

    .tab-count {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 20px;
      height: 18px;
      padding: 0 6px;
      border-radius: 999px;
      background: var(--at-accent-subtle);
      color: var(--at-accent);
      font-size: 11px;
    }
  }
}

.tab-panel {
  animation: fadeIn 0.25s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

// 录入面板布局
.form-layout {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: var(--at-space-5);
  align-items: start;

  @media (max-width: 900px) {
    grid-template-columns: 1fr;
  }
}

.section-nav {
  position: sticky;
  top: var(--at-space-4);
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--at-space-3);
  background: var(--at-bg);
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-lg);
  box-shadow: var(--at-shadow);

  @media (max-width: 900px) {
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border-radius: var(--at-radius-sm);
    color: var(--at-muted);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover {
      background: var(--at-surface);
      color: var(--at-fg);
    }

    &.active {
      background: var(--at-accent-subtle);
      color: var(--at-accent);
    }
  }
}

// 卡片
.form-card {
  background: var(--at-bg);
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-lg);
  box-shadow: var(--at-shadow);
  padding: var(--at-space-6);
  transition: box-shadow 0.2s ease;

  &:hover {
    box-shadow: var(--at-shadow-hover);
  }
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--at-space-5);

  h3 {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
    color: var(--at-fg);
    letter-spacing: -0.02em;
  }
}

// 表单分区标题
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--at-muted);
  margin: var(--at-space-6) 0 var(--at-space-4);
  padding-bottom: var(--at-space-2);
  border-bottom: 1px solid var(--at-border);

  &::before {
    content: '';
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--at-accent);
  }

  &:first-of-type {
    margin-top: 0;
  }
}

// 表单网格
.form-grid {
  display: grid;
  gap: var(--at-space-4);

  &.grid-4 { grid-template-columns: repeat(4, 1fr); }
  &.grid-3 { grid-template-columns: repeat(3, 1fr); }
  &.grid-2 { grid-template-columns: repeat(2, 1fr); }

  @media (max-width: 1200px) {
    &.grid-4,
    &.grid-3,
    &.grid-2 { grid-template-columns: repeat(2, 1fr); }
  }
  @media (max-width: 768px) {
    &.grid-4,
    &.grid-3,
    &.grid-2 { grid-template-columns: 1fr; }
  }
}

// 标签统一样式
:deep(.el-form-item__label) {
  font-size: 12px !important;
  font-weight: 700 !important;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--at-muted) !important;
  line-height: 1.4 !important;
  padding-bottom: 4px !important;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: var(--at-space-3);
}

.kb-target-hint {
  margin-top: var(--at-space-3);
}

// 媒体区
.media-gallery {
  display: flex;
  flex-direction: column;
  gap: var(--at-space-4);
}

.media-paste-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--at-space-2);
  padding: var(--at-space-6);
  border: 2px dashed var(--at-border-strong);
  border-radius: var(--at-radius-md);
  background: var(--at-surface);
  color: var(--at-muted);
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: center;
  outline: none;

  &:hover,
  &:focus {
    border-color: var(--at-accent);
    background: var(--at-accent-subtle);
  }

  &.uploading {
    opacity: 0.6;
    pointer-events: none;
  }

  .paste-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--at-fg);
  }

  .paste-sub,
  .paste-formats {
    margin: 0;
    font-size: 13px;
    color: var(--at-muted);
  }
}

.media-items {
  display: flex;
  flex-wrap: wrap;
  gap: var(--at-space-3);
}

.media-card {
  position: relative;
  width: 180px;
  padding: var(--at-space-2);
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-md);
  background: var(--at-bg);
  box-shadow: var(--at-shadow);

  .media-card-preview {
    width: 100%;
    height: 120px;
    object-fit: cover;
    border-radius: var(--at-radius-sm);
  }

  .media-card-unknown {
    width: 100%;
    height: 120px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    color: var(--at-muted);
    word-break: break-all;
    padding: var(--at-space-2);
  }

  .media-card-delete {
    margin-top: var(--at-space-2);
    width: 100%;
  }
}

// 操作按钮
.form-actions {
  margin-top: var(--at-space-6);
  display: flex;
  gap: var(--at-space-3);
  padding-top: var(--at-space-5);
  border-top: 1px solid var(--at-border);
}

// 列表头部
.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--at-space-4);
  flex-wrap: wrap;
  gap: var(--at-space-3);

  h3 {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
    color: var(--at-fg);
    letter-spacing: -0.02em;
  }
}

.filter-row {
  display: flex;
  align-items: center;
  gap: var(--at-space-3);
  flex-wrap: wrap;
}

.list-group-filter {
  margin: var(--at-space-4) 0;
  display: flex;
  align-items: center;
  gap: var(--at-space-3);
}

// 样本列表 — Linear 风格
.sample-list {
  display: flex;
  flex-direction: column;
  gap: var(--at-space-4);
}

.sample-group {
  display: flex;
  flex-direction: column;
  gap: var(--at-space-2);
}

.group-header {
  display: flex;
  align-items: center;
  gap: var(--at-space-2);
  padding: var(--at-space-2) 0;
  margin-bottom: var(--at-space-1);
  border-bottom: 1px solid var(--at-border);

  .group-title {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--at-muted);
  }

  .group-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 18px;
    padding: 0 6px;
    border-radius: 999px;
    background: var(--at-surface);
    color: var(--at-muted);
    font-size: 11px;
    font-weight: 600;
  }
}

.sample-row {
  display: flex;
  align-items: stretch;
  background: var(--at-bg);
  border: 1px solid var(--at-border);
  border-left: 4px solid transparent;
  border-radius: var(--at-radius-md);
  box-shadow: var(--at-shadow);
  cursor: pointer;
  transition: box-shadow 0.2s ease, transform 0.12s ease, border-color 0.15s ease;
  overflow: hidden;

  &:hover {
    box-shadow: var(--at-shadow-hover);
    border-color: var(--at-border-strong);
    transform: translateY(-1px);
  }

  &.risk-border-低 { border-left-color: var(--at-success); }
  &.risk-border-中 { border-left-color: var(--at-warn); }
  &.risk-border-高 { border-left-color: var(--at-danger); }
}

.row-main {
  flex: 1;
  padding: var(--at-space-4);
  min-width: 0;
}

.row-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.row-id {
  font-size: 12px;
  color: var(--at-meta);
  font-weight: 700;
}

.row-date {
  margin-left: auto;
  font-size: 12px;
  color: var(--at-meta);
}

.row-quote {
  font-size: 15px;
  font-weight: 500;
  color: var(--at-fg);
  line-height: 1.5;
  margin-bottom: 8px;
  max-height: 70px;
  overflow: hidden;

  :deep(img) { display: none; }
  :deep(.empty) { color: var(--at-muted); }
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--at-muted);

  > span {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    background: var(--at-surface);
    border-radius: var(--at-radius-sm);

    .el-icon {
      font-size: 12px;
    }
  }
}

.row-side {
  width: 150px;
  border-left: 1px solid var(--at-border);
  padding: var(--at-space-4);
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--at-surface);
}

.row-risk-badge {
  display: inline-flex;
  width: fit-content;
  padding: 2px 8px;
  border-radius: var(--at-radius-sm);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;

  &.risk-低 { background: #dcfce7; color: #166534; }
  &.risk-中 { background: #ffedd5; color: #9a3412; }
  &.risk-高 { background: #fee2e2; color: #991b1b; }
}

.row-auto {
  font-size: 12px;
  font-weight: 600;
  color: var(--at-muted);
}

.row-actions {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

// 空状态
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--at-space-8) var(--at-space-4);
  color: var(--at-muted);
  text-align: center;

  .empty-title {
    margin: var(--at-space-3) 0 4px;
    font-size: 18px;
    font-weight: 600;
    color: var(--at-fg);
  }

  .empty-sub {
    margin: 0 0 var(--at-space-4);
    font-size: 14px;
    color: var(--at-muted);
  }
}

.pagination-bar {
  margin-top: var(--at-space-6);
  display: flex;
  justify-content: flex-end;
}

// 详情抽屉
.detail-body {
  padding-bottom: var(--at-space-5);
}

.detail-section {
  margin-top: var(--at-space-5);

  h4 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 var(--at-space-3);
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--at-muted);

    &::before {
      content: '';
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: var(--at-accent);
    }
  }
}

.rich-preview {
  background: var(--at-surface);
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-md);
  padding: var(--at-space-4);
  font-size: 15px;
  line-height: 1.6;
  min-height: 60px;
  color: var(--at-fg);

  :deep(img) {
    max-width: 100%;
    max-height: 300px;
    border-radius: var(--at-radius-sm);
    display: block;
    margin: 8px 0;
  }
  :deep(.empty) { color: var(--at-muted); }
}

// Element Plus 组件在本页内的 Airtable 风格微调
.contract-preview {
  background: #f8fbff;
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-md);
  padding: var(--at-space-4);
  font-size: 14px;
  line-height: 1.7;

  p {
    margin: 0 0 8px;
  }
}

.expected-turns {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}

.expected-turn {
  background: #fff;
  border: 1px solid var(--at-border);
  border-radius: var(--at-radius-sm);
  padding: var(--at-space-3);
}

:deep(.el-button--primary) {
  --el-button-bg-color: var(--at-accent);
  --el-button-border-color: var(--at-accent);
  --el-button-hover-bg-color: var(--at-accent-hover);
  --el-button-hover-border-color: var(--at-accent-hover);
  border-radius: var(--at-radius-md);
  font-weight: 600;
}

:deep(.el-button:not(.el-button--primary):not(.el-button--danger)) {
  border-radius: var(--at-radius-md);
  font-weight: 600;
}

:deep(.el-input__wrapper),
:deep(.el-textarea__inner) {
  border-radius: var(--at-radius-sm);
  box-shadow: 0 0 0 1px var(--at-border) inset;
}

:deep(.el-input__wrapper.is-focus),
:deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px var(--at-accent) inset, 0 0 0 3px var(--at-accent-subtle);
}

:deep(.el-select .el-input__wrapper) {
  border-radius: var(--at-radius-sm);
}

:deep(.el-tag) {
  border-radius: var(--at-radius-sm);
  font-weight: 600;
  border: none;
}

:deep(.el-tag--warning) {
  background: #fff7ed;
  color: #9a3412;
}

:deep(.el-tag--success) {
  background: #f0fdf4;
  color: #166534;
}

:deep(.el-tag--info) {
  background: var(--at-surface);
  color: var(--at-muted);
}

:deep(.el-tag--primary) {
  background: var(--at-accent-subtle);
  color: var(--at-accent);
}

// 覆盖富文本编辑器，使其融入 Airtable 风格
:deep(.rich-editor) {
  border-color: var(--at-border);
  border-radius: var(--at-radius-sm);
  background: var(--at-bg);

  .editor-toolbar {
    background: var(--at-surface);
    border-color: var(--at-border);
  }

  .tool-btn {
    color: var(--at-muted);
    border-radius: var(--at-radius-sm);

    &:hover {
      background: var(--at-bg);
      color: var(--at-accent);
    }
  }

  .toolbar-divider,
  .editor-tip {
    border-color: var(--at-border);
  }

  .editor-tip {
    background: var(--at-surface);
    color: var(--at-meta);
  }

  &.focused {
    border-color: var(--at-accent);
    box-shadow: 0 0 0 1px var(--at-accent) inset, 0 0 0 3px var(--at-accent-subtle);
  }
}

// 抽屉内描述列表
:deep(.el-descriptions__body) {
  background: var(--at-surface);
  border-radius: var(--at-radius-md);
  border: 1px solid var(--at-border);
}

:deep(.el-descriptions__label) {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--at-muted);
  background: transparent;
}

:deep(.el-descriptions__content) {
  color: var(--at-fg);
  font-weight: 500;
}

// 分页
:deep(.el-pagination.is-background .el-pager li.is-active) {
  background-color: var(--at-accent);
}
</style>
