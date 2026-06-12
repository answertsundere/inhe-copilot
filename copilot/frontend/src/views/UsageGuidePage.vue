<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'

type DepartmentKey = 'serviceTest' | 'serviceKnowledge' | 'product' | 'operation' | 'agent'
type DepartmentNavCard = {
  key: string
  title: string
  desc: string
  tone: string
  target?: DepartmentKey
  children?: Array<{ key: DepartmentKey; title: string; desc: string }>
}

const activeDepartment = ref<DepartmentKey>('serviceTest')

// Lazy image loaders — Vite generates dynamic imports; images are NOT bundled into the main chunk.
// Each WebP stays as a separate file and is only fetched when the loader is called.
const imageLoaders = import.meta.glob<{ default: string }>(
  '../assets/guide/*-guide-*.{webp,png}',
  { eager: false },
)

// Track which departments have already been loaded (avoid re-fetching)
const loadedDepartments = ref<Set<DepartmentKey>>(new Set())

// Resolved image URLs per department (populated on demand)
const imageUrls = ref<Record<DepartmentKey, Record<string, string>>>({
  serviceTest: {},
  serviceKnowledge: {},
  product: {},
  operation: {},
  agent: {},
})

// Map department → image file names
const departmentFiles: Record<DepartmentKey, string[]> = {
  serviceTest: [
    'service-guide-01.webp',
    'service-guide-02.webp',
    'service-guide-03.webp',
    'service-guide-04.webp',
    'service-guide-05.png',
  ],
  serviceKnowledge: [
    'service-knowledge-guide-01.webp',
    'service-knowledge-guide-02.webp',
    'service-knowledge-guide-03.webp',
    'service-knowledge-guide-04.webp',
  ],
  product: [
    'product-guide-01.webp',
    'product-guide-02.webp',
    'product-guide-03.webp',
    'product-guide-04.webp',
    'product-guide-05.webp',
    'product-guide-06.webp',
  ],
  operation: [
    'operation-guide-01.webp',
    'operation-guide-02.webp',
    'operation-guide-03.webp',
  ],
  agent: [
    'agent-guide-01.webp',
    'agent-guide-02.webp',
    'agent-guide-03.webp',
  ],
}

async function loadDepartmentImages(dept: DepartmentKey) {
  if (loadedDepartments.value.has(dept)) return
  loadedDepartments.value = new Set(loadedDepartments.value).add(dept)

  const files = departmentFiles[dept]
  const entries = await Promise.all(
    files.map(async (file) => {
      const key = `../assets/guide/${file}`
      const loader = imageLoaders[key]
      if (!loader) return null
      const mod = await loader()
      return [file, mod.default] as const
    }),
  )
  const map: Record<string, string> = {}
  for (const entry of entries) {
    if (entry) map[entry[0]] = entry[1]
  }
  imageUrls.value = { ...imageUrls.value, [dept]: map }
}

function getImageUrl(dept: DepartmentKey, file: string): string {
  return imageUrls.value[dept][file] || ''
}

// Pre-load service test images on mount, then react to department switches
onMounted(() => loadDepartmentImages('serviceTest'))
watch(activeDepartment, (dept) => loadDepartmentImages(dept))

const guideActions: Record<DepartmentKey, { actionText: string; actionPath: string }> = {
  serviceTest: { actionText: '进入真实测试', actionPath: '/ask/real-test' },
  serviceKnowledge: { actionText: '进入问答资料', actionPath: '/ask/kb-admin/qa' },
  product: { actionText: '进入商品资料', actionPath: '/ask/kb-admin/products' },
  operation: { actionText: '进入活动规则中心', actionPath: '/ask/kb-admin/shop-rules' },
  agent: { actionText: '进入 AI 更新中心', actionPath: '/ask/kb-admin/ai-updates' },
}

const departmentCards: DepartmentNavCard[] = [
  {
    key: 'service',
    title: '使用说明：客服部',
    desc: '测试页面、资料/SOP',
    tone: 'blue',
    children: [
      { key: 'serviceTest', title: '测试页面', desc: '真实测试、验收反馈' },
      { key: 'serviceKnowledge', title: '资料/SOP', desc: '问答资料、售后步骤' },
    ],
  },
  {
    key: 'product',
    title: '使用说明：货品部',
    desc: '新增商品、补全字段、编辑保存',
    target: 'product',
    tone: 'green',
  },
  {
    key: 'operation',
    title: '使用说明：运营',
    desc: '活动规则、优惠券、赠品、价保口径',
    target: 'operation',
    tone: 'orange',
  },
  {
    key: 'agent',
    title: '使用说明：Agent 开发',
    desc: '看失败、重建索引、确认 AI 是否学到',
    target: 'agent',
    tone: 'purple',
  },
]

const guideConfig = {
  serviceTest: {
    title: '客服部：测试页面怎么操作',
    desc: '客服测试时按真实千牛场景填写，发现回复不对就沉淀问题，后续才能越改越准。',
    shots: [
      { title: '1. 打开真实测试面板，选择要测的用例', file: 'service-guide-01.webp' },
      { title: '2. 按千牛侧边栏信息填写客户消息、商品或订单', file: 'service-guide-02.webp' },
      { title: '3. 运行后检查建议回复是否能直接发给客户', file: 'service-guide-03.webp' },
      { title: '4. 不合格就保存验收或提交反馈，方便后续优化', file: 'service-guide-04.webp' },
      { title: '5. 查看上下文和图片区域，按真实聊天继续测试', file: 'service-guide-05.png' },
    ],
    steps: [
      '打开真实测试面板，先选一个测试用例，或直接输入真实客户消息。',
      '售前按千牛侧边栏商品名称测试；售后按订单号、商品名称、SKU 等真实字段测试。',
      '重点看回复是否像真人客服、是否回答了客户问题、有没有乱承诺。',
      '如果不通过，选择问题类型，写下客服认为正确的回复或备注，再提交反馈。',
    ],
  },
  serviceKnowledge: {
    title: '客服部：问答资料和 SOP 怎么维护',
    desc: '客服把真实高频问题、优秀回复、安抚说法和售后处理步骤维护进去，后面测试失败时才能知道该补资料还是改流程。',
    shots: [
      { title: '1. 进入问答资料或售后处理页面', file: 'service-knowledge-guide-01.webp' },
      { title: '2. 搜索已有资料，确认是新增还是修改', file: 'service-knowledge-guide-02.webp' },
      { title: '3. 按真实客服话术补充问题和回复', file: 'service-knowledge-guide-03.webp' },
      { title: '4. 保存后回到测试页面复测', file: 'service-knowledge-guide-04.webp' },
    ],
    steps: [
      '问答资料主要维护客户经常问的问题，例如怎么安装、怎么清洁、有没有味道、和别家有什么区别等。',
      '新增或修改问答时，先写清楚客户常见问法，再写客服可以直接复制的回复，避免只写内部备注。',
      '遇到退换、少件、错发、破损、补配件、拦截、改地址等售后处理问题，到售后处理页维护 SOP。',
      'SOP 要写清楚客服第一步问什么、需要客户提供什么、能承诺什么、哪些情况必须转人工或主管确认。',
      '测试页面发现回复不好时，不要只说“不对”，要把正确客服话术或处理步骤补回问答资料/SOP，再复测同一条问题。',
    ],
  },
  product: {
    title: '货品部：商品资料怎么填写',
    desc: '商品资料补得越完整，客服助手回答材质、尺寸、承重、适用年龄、配件和安装问题时越稳定。',
    shots: [
      { title: '1. 在这里新增商品', file: 'product-guide-01.webp' },
      { title: '2. 在商品资料页新增商品', file: 'product-guide-02.webp' },
      { title: '3. 查看完整度，点详情补资料', file: 'product-guide-03.webp' },
      { title: '4. 点编辑进入填写状态', file: 'product-guide-04.webp' },
      { title: '5. 按字段补完整商品资料', file: 'product-guide-05.webp' },
      { title: '6. 商品有更新时先搜索再维护', file: 'product-guide-06.webp' },
    ],
    steps: [
      '如果是新增商品，先点商品资料页右上角"新增商品"。',
      '如果是已有商品，先在左侧类目或搜索框里找商品名称、商品编码。',
      '看列表里的完整度和健康标签：缺材质、缺尺寸、缺承重、缺年龄、缺配件等都需要补。',
      '点商品右侧"详情"，再点右下角"编辑"。',
      '把材质、尺寸、承重/容量、适用年龄、配件清单、安装方式、质保期、物流属性尽量补完整。',
      '填完后点"保存"。商品资料变化后，记得回来同步维护。',
    ],
  },
  operation: {
    title: '运营：活动规则怎么维护',
    desc: '运营把优惠券、赠品、价保、发票、活动页面口径维护清楚，客服才能按统一规则回复客户。',
    shots: [
      { title: '1. 进入活动规则中心，查看当前规则', file: 'operation-guide-01.webp' },
      { title: '2. 新增或编辑优惠券、赠品、价保等规则', file: 'operation-guide-02.webp' },
      { title: '3. 保存后检查列表状态和客服回复口径', file: 'operation-guide-03.webp' },
    ],
    steps: [
      '进入活动规则中心，先看当前活动、优惠券、赠品、价保等规则是否已经存在。',
      '没有规则就点"新增规则"，已有规则就点"编辑"。',
      '填写适用范围、规则内容、客服回复口径和不能承诺的内容。',
      '保存后回到列表检查状态，活动变化时及时更新，避免客服按旧规则回复。',
    ],
  },
  agent: {
    title: 'Agent 开发：失败和索引怎么处理',
    desc: '维护人员看失败清单、RAG 同步状态和知识更新情况，确认 AI 是否真的学到。',
    shots: [
      { title: '1. 查看失败清单和失败原因分布', file: 'agent-guide-01.webp' },
      { title: '2. 打开失败详情，判断要补资料还是修流程', file: 'agent-guide-02.webp' },
      { title: '3. 知识更新后重建检索索引并复测', file: 'agent-guide-03.webp' },
    ],
    steps: [
      '进入 AI 更新中心，先看未关闭失败、未学习、索引未同步和索引失败数量。',
      '点失败记录"详情"，看客户问题、AI 回复、根因、检索证据和修复记录。',
      '如果是资料缺失，分派给对应部门补资料；如果是流程问题，记录给 Agent 开发处理。',
      '知识更新后重建检索索引，再回真实测试面板复测同一条问题。',
    ],
  },
}

const activeGuide = computed(() => guideConfig[activeDepartment.value])
const activeAction = computed(() => guideActions[activeDepartment.value])

function openPath(path: string) {
  window.open(path, '_blank')
}
</script>

<template>
  <div class="usage-page">
    <section class="hero-panel">
      <div>
        <h2>使用说明</h2>
        <p>先点部门入口，下面只显示当前部门的操作说明；后续继续加部门也不会变成长页面。</p>
      </div>
      <el-button type="primary" @click="openPath(activeAction.actionPath)">{{ activeAction.actionText }}</el-button>
    </section>

    <section class="department-page-nav">
      <div
        v-for="card in departmentCards"
        :key="card.key"
        class="department-card"
        :class="[card.tone, { active: card.target === activeDepartment || card.children?.some(child => child.key === activeDepartment) }]"
      >
        <button
          v-if="card.target"
          class="department-main"
          type="button"
          @click="activeDepartment = card.target"
        >
          <span class="department-title">{{ card.title }}</span>
          <span class="department-desc">{{ card.desc }}</span>
        </button>
        <template v-else>
          <div class="department-main static">
            <span class="department-title">{{ card.title }}</span>
            <span class="department-desc">{{ card.desc }}</span>
          </div>
          <div class="sub-guide-list">
            <button
              v-for="child in card.children"
              :key="child.key"
              class="sub-guide"
              :class="{ active: activeDepartment === child.key }"
              type="button"
              @click="activeDepartment = child.key"
            >
              <span>{{ child.title }}</span>
              <small>{{ child.desc }}</small>
            </button>
          </div>
        </template>
      </div>
    </section>

    <section class="guide-panel">
      <div class="guide-head">
        <div>
          <h3>{{ activeGuide.title }}</h3>
          <p>{{ activeGuide.desc }}</p>
        </div>
        <el-button type="primary" @click="openPath(activeAction.actionPath)">{{ activeAction.actionText }}</el-button>
      </div>

      <div v-if="activeGuide.shots.length" class="shot-list">
        <div v-for="shot in activeGuide.shots" :key="shot.title" class="screenshot-card">
          <div class="shot-caption">{{ shot.title }}</div>
          <div class="screenshot-wrap">
            <img
              v-if="getImageUrl(activeDepartment, shot.file)"
              :src="getImageUrl(activeDepartment, shot.file)"
              :alt="shot.title"
              loading="lazy"
              decoding="async"
            />
            <div v-else class="shot-placeholder">加载中…</div>
          </div>
        </div>
      </div>
      <div v-else class="empty-shot-note">这一部分先按文字步骤操作，后续补充截图后会显示在这里。</div>

      <div class="step-box">
        <h4>操作顺序</h4>
        <ol>
          <li v-for="step in activeGuide.steps" :key="step">{{ step }}</li>
        </ol>
      </div>
    </section>
  </div>
</template>

<style scoped>
.usage-page { padding: 16px; }
.hero-panel, .department-page-nav, .guide-panel { background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.hero-panel { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 20px 24px; margin-bottom: 12px; }
.hero-panel h2 { margin: 0; font-size: 22px; color: #1f2d3d; }
.hero-panel p { margin: 6px 0 0; color: #606266; font-size: 14px; }
.department-page-nav { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; padding: 14px; margin-bottom: 16px; }
.department-card { border: 1px solid #d7dfec; border-radius: 8px; background: #fbfcfe; padding: 14px; text-align: left; transition: border-color .15s, box-shadow .15s, transform .15s, background .15s; }
.department-card:hover { border-color: #409eff; box-shadow: 0 6px 16px rgba(64,158,255,.14); transform: translateY(-1px); }
.department-card.active { background: #f0f7ff; border-color: #409eff; box-shadow: 0 6px 16px rgba(64,158,255,.16); }
.department-card.blue { border-left: 4px solid #409eff; }
.department-card.green { border-left: 4px solid #67c23a; }
.department-card.orange { border-left: 4px solid #e6a23c; }
.department-card.purple { border-left: 4px solid #8b5cf6; }
.department-main { display: block; width: 100%; border: 0; background: transparent; padding: 0; text-align: left; cursor: pointer; color: inherit; }
.department-main.static { cursor: default; }
.department-title { display: block; font-size: 18px; font-weight: 800; color: #1f2d3d; margin-bottom: 6px; }
.department-desc { display: block; font-size: 13px; color: #606266; line-height: 1.45; }
.sub-guide-list { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
.sub-guide { border: 1px solid #d7dfec; border-radius: 6px; background: #fff; padding: 9px 10px; text-align: left; cursor: pointer; }
.sub-guide.active { border-color: #409eff; background: #ecf5ff; }
.sub-guide span { display: block; color: #1f2d3d; font-weight: 800; font-size: 13px; margin-bottom: 3px; }
.sub-guide small { display: block; color: #606266; font-size: 12px; line-height: 1.35; }
.guide-panel { padding: 18px; margin-bottom: 16px; }
.guide-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; }
.guide-head h3 { margin: 0; font-size: 17px; color: #303133; }
.guide-head p { margin: 6px 0 0; color: #606266; font-size: 13px; line-height: 1.6; }
.shot-list { display: grid; grid-template-columns: 1fr; gap: 14px; }
.screenshot-card { border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; background: #fbfcfe; }
.shot-caption { font-weight: 700; color: #303133; margin-bottom: 8px; font-size: 14px; }
.screenshot-wrap { border: 1px solid #d7dfec; border-radius: 8px; overflow: hidden; background: #fff; }
.screenshot-wrap img { display: block; width: 100%; height: auto; aspect-ratio: 16 / 9; object-fit: contain; background: #f5f7fa; }
.shot-placeholder { display: flex; align-items: center; justify-content: center; min-height: 120px; color: #909399; font-size: 14px; background: #f5f7fa; border-radius: 8px; }
.empty-shot-note { border: 1px dashed #cbd5e1; border-radius: 8px; padding: 14px; color: #64748b; background: #f8fafc; font-size: 13px; }
.step-box { border: 1px solid #e4e7ed; border-radius: 8px; padding: 14px; background: #fbfcfe; margin-top: 12px; }
.step-box h4 { margin: 0 0 8px; font-size: 15px; color: #303133; }
.step-box ol { margin: 0; padding-left: 18px; }
.step-box li { margin: 7px 0; font-size: 13px; line-height: 1.55; color: #303133; }
@media (max-width: 1180px) {
  .department-page-nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .hero-panel { display: block; }
  .hero-panel .el-button { margin-top: 12px; }
  .department-page-nav { grid-template-columns: 1fr; }
  .guide-head { display: block; }
  .guide-head .el-button { margin-top: 12px; }
}
</style>
