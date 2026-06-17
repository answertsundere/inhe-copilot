<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { getDashboardStats } from '../api/dashboard'
import {
  Goods,
  ChatDotRound,
  Warning,
  UserFilled,
  CircleCheck,
  Connection,
  Tickets,
  DataAnalysis,
  Van,
} from '@element-plus/icons-vue'

interface DashboardStats {
  total_products: number
  total_qa: number
  total_sop: number
  total_cases: number
  total_traces: number
  total_feedback: number
  qa_by_status: Record<string, number>
  qa_by_risk_level: Record<string, number>
  review_pending_count: number
  review_stats: Record<string, number>
  recent_changes: Array<{
    id: number
    target_type: string
    target_id: number
    target_title: string
    action: string
    performed_by: string
    created_at: string
  }>
}

interface ResponsibilityItem {
  group: string
  role: string
  owner: string
  icon: any
  color: string
  needDo: string
  fillWhere: string
  checkCycle: string
  successStandard: string
  route: string
}

const CONFIG_KEY = 'inhe_kb_dashboard_org_config_v3'
const loading = ref(true)
const editMode = ref(false)
const stats = ref<DashboardStats | null>(null)

const defaultResponsibilities: ResponsibilityItem[] = [
  {
    group: '跨部门',
    role: '货品 / 商品部',
    owner: '待填写',
    icon: Goods,
    color: '#2563eb',
    needDo: '补商品资料：商品编码、店铺显示名称、材质、尺寸、承重、适用年龄、配件、安装图、款式差异。',
    fillWhere: '商品资料页',
    checkCycle: '上新当天补齐，重点商品每周检查。',
    successStandard: '客服问到商品问题时，AI 能先对上具体商品，再按已确认资料回答。',
    route: '/products',
  },
  {
    group: '客服体系',
    role: '客服部 / 回复话术检查',
    owner: '待填写',
    icon: UserFilled,
    color: '#059669',
    needDo: '检查商品咨询、物流、发货、优惠等回复话术，补真实客户问题、优秀回复、人工改写、错误案例。',
    fillWhere: '问答资料页、案例库、测试记录',
    checkCycle: '每天补高频问题和答不好的场景，每周复盘物流/发货等高频话术。',
    successStandard: 'AI 回复像客服能直接复制，语气自然，物流等问题能给出清楚下一步。',
    route: '/qa',
  },
  {
    group: '客服体系',
    role: '客服部 / 售后 SOP',
    owner: '待填写',
    icon: Van,
    color: '#d97706',
    needDo: '新增、修改、删除售后处理 SOP：拦截、改地址、退换、少件、错发、破损、补配件、物流异常。',
    fillWhere: '售后处理页',
    checkCycle: '出现新售后场景当天补充，每周统一检查和优化。',
    successStandard: '客户问售后问题时，AI 能给出清楚的处理步骤，不乱承诺。',
    route: '/sop',
  },
  {
    group: '跨部门',
    role: '运营 / 店铺',
    owner: '待填写',
    icon: Tickets,
    color: '#7c3aed',
    needDo: '补优惠、赠品、价保、发票、活动规则、店铺页面口径、售前不能承诺的内容。',
    fillWhere: '活动规则中心',
    checkCycle: '活动前补齐，活动中每天检查。',
    successStandard: '客户问活动、优惠、赠品、发票时，AI 说法和店铺当前页面一致。',
    route: '/shop-rules',
  },
  {
    group: '项目支持',
    role: 'AI 维护人员 / 知识库管理员',
    owner: '待填写',
    icon: DataAnalysis,
    color: '#0f766e',
    needDo: '把各岗位提供的内容整理成 AI 能查到的资料，处理查不到、答偏、语气不好等问题。',
    fillWhere: 'AI 更新中心、测试记录',
    checkCycle: '每天看失败案例，每周做一次集中优化。',
    successStandard: 'AI 能找到正确资料，回答有依据，客服测试通过率持续提升。',
    route: '/ai-updates',
  },
]

const responsibilities = reactive<ResponsibilityItem[]>(
  defaultResponsibilities.map((item) => ({ ...item })),
)

const mapNodes = computed(() => {
  const pendingReview = stats.value?.review_pending_count ?? 0
  const feedback = stats.value?.total_feedback ?? 0
  const cases = stats.value?.total_cases ?? 0
  const highRisk = stats.value?.qa_by_risk_level?.high ?? 0
  const mediumRisk = stats.value?.qa_by_risk_level?.medium ?? 0

  return [
    {
      title: '货品',
      tag: '补商品资料',
      text: '商品编码、店铺名称、材质、尺寸、承重、适龄、配件、安装图。',
      route: '/products',
      todo: [
        { label: '待补', value: Math.max(0, Math.round((stats.value?.total_products ?? 0) * 0.08)) },
        { label: '待确认', value: Math.round(pendingReview * 0.25) },
      ],
    },
    {
      title: '客服',
      tag: '检查回复话术',
      text: '客户常问问题、物流回复、金牌回复、安抚方式、人工改写。',
      route: '/qa',
      todo: [
        { label: '错误案例', value: cases },
        { label: '待沉淀', value: feedback },
      ],
    },
    {
      title: '客服售后',
      tag: '优化售后 SOP',
      text: '发货、拦截、退换、少件、错发、破损、物流异常。',
      route: '/sop',
      todo: [
        { label: '待补', value: Math.max(0, Math.round((stats.value?.total_sop ?? 0) * 0.05)) },
        { label: '待确认', value: Math.round(pendingReview * 0.2) },
      ],
    },
    {
      title: '运营',
      tag: '维护活动规则',
      text: '优惠、赠品、价保、发票、活动规则、页面口径。',
      route: '/shop-rules',
      todo: [
        { label: '待更新', value: 6 },
        { label: '活动规则', value: 3 },
      ],
    },
    {
      title: '主管/质检',
      tag: '确认能不能说',
      text: '确认能直接回答、要先核实、必须转人工的边界。',
      route: '/reviews',
      todo: [
        { label: '待确认', value: pendingReview },
        { label: '高风险', value: highRisk + mediumRisk },
      ],
    },
    {
      title: 'AI 维护人员',
      tag: '整理给 AI 查',
      text: '把资料整理好，让 AI 能查到、用对、说得自然。',
      route: '/ai-updates',
      todo: [
        { label: '待整理', value: pendingReview + feedback },
        { label: '测试失败', value: cases },
      ],
    },
    {
      title: '测试/反馈',
      tag: '发现问题再回流',
      text: '客服用真实问题测试，发现答错、答偏、语气不好就分派。',
      route: '/traces',
      todo: [
        { label: '待回流', value: feedback },
        { label: '待复测', value: cases },
      ],
    },
  ]
})

const evolveSteps = [
  '各岗位补资料',
  '主管确认能不能这样说',
  '整理给 AI 客服助手',
  '客服用真实问题测试',
  '记录错误案例和优秀回复',
  '分给负责人继续修改',
]

const plainRules = [
  'AI 只给客服建议，不自动发送消息。',
  '没有确认过的商品信息，不能让 AI 直接猜。',
  '安全、材质、承重、适用年龄、售后承诺这类问题，要先确认再回答。',
  '客服测试和反馈越多，AI 越像金牌客服。',
]

const riskItems = computed(() => {
  if (!stats.value?.qa_by_risk_level) return []
  const labels: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险', critical: '严重风险' }
  const colors: Record<string, string> = { low: '#059669', medium: '#d97706', high: '#dc2626', critical: '#991b1b' }
  const total = Object.values(stats.value.qa_by_risk_level).reduce((a, b) => a + b, 0) || 1
  return Object.entries(stats.value.qa_by_risk_level).map(([key, val]) => ({
    label: labels[key] || key,
    count: val,
    percent: Math.round((val / total) * 100),
    color: colors[key] || '#64748b',
  }))
})

const statusItems = computed(() => {
  if (!stats.value?.qa_by_status) return []
  const labels: Record<string, string> = { draft: '草稿', pending_review: '待审核', published: '已发布', rejected: '已驳回' }
  const colors: Record<string, string> = { draft: '#64748b', pending_review: '#d97706', published: '#059669', rejected: '#dc2626' }
  const total = Object.values(stats.value.qa_by_status).reduce((a, b) => a + b, 0) || 1
  return Object.entries(stats.value.qa_by_status).map(([key, val]) => ({
    label: labels[key] || key,
    count: val,
    percent: Math.round((val / total) * 100),
    color: colors[key] || '#64748b',
  }))
})

function loadLocalConfig() {
  const raw = localStorage.getItem(CONFIG_KEY)
  if (!raw) return
  try {
    const saved = JSON.parse(raw) as Partial<ResponsibilityItem>[]
    responsibilities.splice(
      0,
      responsibilities.length,
      ...defaultResponsibilities.map((item, index) => ({
        ...item,
        ...(saved[index] || {}),
        icon: item.icon,
        color: item.color,
        route: item.route,
      })),
    )
  } catch (e) {
    console.warn('Failed to load dashboard config', e)
  }
}

function saveLocalConfig() {
  const payload = responsibilities.map(({ group, role, owner, needDo, fillWhere, checkCycle, successStandard }) => ({
    group,
    role,
    owner,
    needDo,
    fillWhere,
    checkCycle,
    successStandard,
  }))
  localStorage.setItem(CONFIG_KEY, JSON.stringify(payload))
  editMode.value = false
}

function resetLocalConfig() {
  localStorage.removeItem(CONFIG_KEY)
  responsibilities.splice(0, responsibilities.length, ...defaultResponsibilities.map((item) => ({ ...item })))
}

const actionTagType = (action: string) => {
  const map: Record<string, string> = { created: 'success', updated: '', deleted: 'danger', submitted: 'warning', published: 'success' }
  return (map[action] || '') as '' | 'success' | 'warning' | 'danger' | 'info'
}

function formatDate(dateStr: string) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function fetchData() {
  loading.value = true
  try {
    const { data } = await getDashboardStats()
    stats.value = data
  } catch (e) {
    console.error('Failed to fetch dashboard stats', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadLocalConfig()
  fetchData()
})
</script>

<template>
  <div class="dashboard-page">
    <el-skeleton :loading="loading" animated :count="1">
      <template #template>
        <el-skeleton-item variant="rect" style="height: 560px; border-radius: 8px" />
      </template>

      <template #default>
        <section class="section-block graph-section">
          <div class="section-head">
            <div>
              <h3>INHE 智能客服协作地图</h3>
            </div>
          </div>
          <div class="knowledge-map">
            <svg class="map-lines" viewBox="0 0 1000 560" preserveAspectRatio="none" aria-hidden="true">
              <line x1="500" y1="280" x2="160" y2="105" />
              <line x1="500" y1="280" x2="500" y2="82" />
              <line x1="500" y1="280" x2="840" y2="105" />
              <line x1="500" y1="280" x2="860" y2="300" />
              <line x1="500" y1="280" x2="690" y2="470" />
              <line x1="500" y1="280" x2="310" y2="470" />
              <line x1="500" y1="280" x2="140" y2="300" />
              <line class="soft-line" x1="160" y1="105" x2="500" y2="82" />
              <line class="soft-line" x1="500" y1="82" x2="840" y2="105" />
              <line class="soft-line" x1="840" y1="105" x2="860" y2="300" />
              <line class="soft-line" x1="860" y1="300" x2="690" y2="470" />
              <line class="soft-line" x1="690" y1="470" x2="310" y2="470" />
              <line class="soft-line" x1="310" y1="470" x2="140" y2="300" />
              <line class="soft-line" x1="140" y1="300" x2="160" y2="105" />
              <line class="feedback-line" x1="140" y1="300" x2="840" y2="105" />
              <line class="feedback-line" x1="140" y1="300" x2="160" y2="105" />
              <line class="feedback-line" x1="140" y1="300" x2="500" y2="82" />
            </svg>
            <RouterLink class="map-center" to="/ai-updates">
              <el-icon><Connection /></el-icon>
              <h4>AI 客服助手</h4>
              <p>根据已确认资料，生成客服可参考的回复</p>
              <span>查看 AI 更新中心</span>
            </RouterLink>

            <RouterLink
              v-for="(node, index) in mapNodes"
              :key="node.title"
              class="map-node"
              :class="`node-${index + 1}`"
              :to="node.route"
            >
              <div class="node-tag">{{ node.tag }}</div>
              <h4>{{ node.title }}</h4>
              <p>{{ node.text }}</p>
              <div class="node-todos">
                <span v-for="todo in node.todo" :key="todo.label">
                  {{ todo.label }} {{ todo.value }}
                </span>
              </div>
            </RouterLink>
          </div>
          <div class="evolve-strip">
            <div v-for="(step, index) in evolveSteps" :key="step" class="evolve-step">
              <span>{{ index + 1 }}</span>
              {{ step }}
            </div>
          </div>
        </section>

        <section class="section-block">
          <div class="section-head">
            <div>
              <h3>谁负责什么</h3>
              <p>这里要写成公司内部能执行的责任表。负责人可以先填姓名，职责也可以随着团队分工继续优化。</p>
            </div>
            <div class="head-actions">
              <el-button v-if="!editMode" type="primary" @click="editMode = true">编辑责任表</el-button>
              <template v-else>
                <el-button type="primary" @click="saveLocalConfig">保存</el-button>
                <el-button @click="editMode = false">取消</el-button>
                <el-button @click="resetLocalConfig">恢复默认</el-button>
              </template>
            </div>
          </div>

          <div class="owner-note">
            当前编辑会先保存在本机浏览器，适合先梳理组织分工；后续需要多人共享时，再接入后台统一保存。
          </div>

          <div class="responsibility-table">
            <div class="table-head">归属</div>
            <div class="table-head">岗位 / 负责人</div>
            <div class="table-head">需要补什么</div>
            <div class="table-head">补到哪里</div>
            <div class="table-head">多久检查一次</div>
            <div class="table-head">怎么判断做好了</div>

            <template v-for="item in responsibilities" :key="item.role">
              <div class="table-cell">
                <el-tag size="small" :type="item.group === '客服体系' ? 'success' : item.group === '跨部门' ? 'primary' : 'info'">
                  {{ item.group }}
                </el-tag>
              </div>
              <div class="table-cell role-cell">
                <div class="role-icon" :style="{ backgroundColor: item.color + '18', color: item.color }">
                  <el-icon><component :is="item.icon" /></el-icon>
                </div>
                <div class="role-copy">
                  <template v-if="editMode">
                    <el-input v-model="item.role" size="small" />
                    <el-input v-model="item.owner" size="small" placeholder="负责人姓名" />
                  </template>
                  <template v-else>
                    <strong>{{ item.role }}</strong>
                    <span>负责人：{{ item.owner }}</span>
                  </template>
                </div>
              </div>
              <div class="table-cell">
                <el-input v-if="editMode" v-model="item.needDo" type="textarea" :rows="3" />
                <span v-else>{{ item.needDo }}</span>
              </div>
              <div class="table-cell">
                <el-input v-if="editMode" v-model="item.fillWhere" type="textarea" :rows="2" />
                <span v-else>{{ item.fillWhere }}</span>
                <RouterLink class="maintain-link" :to="item.route">进入维护</RouterLink>
              </div>
              <div class="table-cell">
                <el-input v-if="editMode" v-model="item.checkCycle" type="textarea" :rows="2" />
                <span v-else>{{ item.checkCycle }}</span>
              </div>
              <div class="table-cell">
                <el-input v-if="editMode" v-model="item.successStandard" type="textarea" :rows="3" />
                <span v-else>{{ item.successStandard }}</span>
              </div>
            </template>
          </div>
        </section>

        <el-row :gutter="16" class="main-row">
          <el-col :span="9">
            <el-card shadow="never" class="principle-card">
              <template #header><span class="chart-title">协作原则</span></template>
              <ul>
                <li v-for="item in plainRules" :key="item">{{ item }}</li>
              </ul>
            </el-card>
          </el-col>
          <el-col :span="15">
            <el-card shadow="never" class="chart-card">
              <template #header><span class="chart-title">当前资料状态</span></template>
              <div class="chart-grid">
                <div>
                  <h4>问题风险分布</h4>
                  <div class="bar-list">
                    <div v-for="item in riskItems" :key="item.label" class="bar-item">
                      <div class="bar-label">{{ item.label }}</div>
                      <div class="bar-track">
                        <div class="bar-fill" :style="{ width: item.percent + '%', backgroundColor: item.color }" />
                      </div>
                      <div class="bar-meta">
                        <span class="bar-count">{{ item.count }}</span>
                        <span>{{ item.percent }}%</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div>
                  <h4>资料状态分布</h4>
                  <div class="bar-list">
                    <div v-for="item in statusItems" :key="item.label" class="bar-item">
                      <div class="bar-label">{{ item.label }}</div>
                      <div class="bar-track">
                        <div class="bar-fill" :style="{ width: item.percent + '%', backgroundColor: item.color }" />
                      </div>
                      <div class="bar-meta">
                        <span class="bar-count">{{ item.count }}</span>
                        <span>{{ item.percent }}%</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <el-card shadow="never" class="recent-card">
          <template #header><span class="chart-title">最近修改记录</span></template>
          <el-table :data="stats?.recent_changes || []" stripe size="small" style="width: 100%">
            <el-table-column prop="target_type" label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.target_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="target_title" label="标题" min-width="240" show-overflow-tooltip />
            <el-table-column prop="action" label="操作" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="actionTagType(row.action)">{{ row.action }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="performed_by" label="操作人" width="130" />
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </template>
    </el-skeleton>
  </div>
</template>

<style scoped>
.dashboard-page {
  max-width: 1480px;
}

.section-block,
.recent-card,
.principle-card,
.chart-card {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  box-shadow: var(--kb-shadow-card);
}

.section-block {
  margin-top: var(--kb-space-4);
  padding: var(--kb-space-5);
}

.graph-section {
  margin-top: 0;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--kb-space-4);
}

.section-head h3 {
  margin: 0;
  color: var(--kb-text-primary);
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
}

.section-head p {
  margin: 6px 0 0;
  color: var(--kb-text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.knowledge-map {
  position: relative;
  min-height: 590px;
  margin-top: 18px;
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  background:
    radial-gradient(circle at center, rgba(79, 106, 246, 0.08) 0 116px, transparent 117px),
    linear-gradient(180deg, var(--kb-bg-page) 0%, var(--kb-bg-card) 100%);
  overflow: hidden;
}

.map-lines {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.map-lines line {
  stroke: var(--kb-accent);
  stroke-width: 1.8;
  stroke-linecap: round;
  opacity: 0.45;
}

.map-lines .soft-line {
  stroke: var(--kb-accent);
  stroke-width: 1.4;
  stroke-dasharray: 6 8;
  opacity: 0.28;
}

.map-lines .feedback-line {
  stroke: var(--kb-warning-text);
  stroke-width: 1.6;
  stroke-dasharray: 4 7;
  opacity: 0.55;
}

.map-center {
  position: absolute;
  z-index: 3;
  left: 50%;
  top: 50%;
  width: 250px;
  min-height: 158px;
  transform: translate(-50%, -50%);
  border: 2px solid var(--kb-accent);
  border-radius: var(--kb-radius-lg);
  padding: 20px 18px;
  text-align: center;
  background: var(--kb-bg-card);
  box-shadow: 0 14px 32px rgba(79, 106, 246, 0.14);
  color: inherit;
  text-decoration: none;
}

.map-center .el-icon {
  color: var(--kb-accent);
  font-size: 28px;
}

.map-center h4 {
  margin: 10px 0 8px;
  color: var(--kb-text-primary);
  font-size: 18px;
  font-weight: 600;
}

.map-center p {
  margin: 0;
  color: var(--kb-text-secondary);
  line-height: 1.6;
}

.map-center span {
  display: inline-block;
  margin-top: 10px;
  color: var(--kb-accent);
  font-size: 12px;
  font-weight: 500;
}

.map-node {
  z-index: 2;
  position: absolute;
  width: 240px;
  min-height: 154px;
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px;
  background: var(--kb-bg-card);
  box-shadow: var(--kb-shadow-card-hover);
  color: inherit;
  text-decoration: none;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.map-node:hover {
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.node-1 { left: 7%; top: 7%; }
.node-2 { left: 39%; top: 4%; }
.node-3 { right: 7%; top: 7%; }
.node-4 { right: 5%; top: 42%; }
.node-5 { right: 18%; bottom: 6%; }
.node-6 { left: 18%; bottom: 6%; }
.node-7 {
  left: 5%;
  top: 42%;
  border-color: var(--kb-warning-bg);
  background: #fffbeb;
}

.node-tag {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--kb-accent-subtle);
  color: var(--kb-accent);
  font-size: 12px;
  font-weight: 500;
}

.map-node h4 {
  margin: 10px 0 0;
  color: var(--kb-text-primary);
  font-size: 15px;
  font-weight: 600;
}

.map-node p {
  margin: 8px 0 0;
  color: var(--kb-text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.node-todos {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.node-todos span {
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--kb-bg-hover);
  color: var(--kb-text-secondary);
  font-size: 12px;
  font-weight: 500;
}

.evolve-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
  padding: 12px;
  border-radius: var(--kb-radius-lg);
  background: var(--kb-success-bg);
}

.evolve-step {
  color: var(--kb-success-text);
  font-size: 13px;
  font-weight: 600;
  text-align: center;
}

.evolve-step span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin-right: 4px;
  border-radius: 50%;
  background: var(--kb-success-text);
  color: #fff;
}

.owner-note {
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: var(--kb-radius-lg);
  background: var(--kb-warning-bg);
  color: var(--kb-warning-text);
  font-size: 13px;
}

.responsibility-table {
  display: grid;
  grid-template-columns: 88px 210px minmax(260px, 1fr) 150px 180px minmax(220px, 0.8fr);
  margin-top: 14px;
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  overflow: hidden;
}

.table-head {
  background: var(--kb-bg-hover);
  color: var(--kb-text-primary);
  font-size: 13px;
  font-weight: 600;
  padding: 11px 12px;
  border-bottom: 1px solid var(--kb-border);
}

.table-cell {
  min-height: 112px;
  padding: 12px;
  border-bottom: 1px solid var(--kb-border);
  color: var(--kb-text-secondary);
  font-size: 13px;
  line-height: 1.65;
  background: var(--kb-bg-card);
}

.role-cell {
  display: flex;
  gap: 10px;
}

.role-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--kb-radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.role-copy {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.role-copy strong {
  color: var(--kb-text-primary);
  font-weight: 600;
}

.role-copy span {
  color: var(--kb-text-secondary);
}

.maintain-link {
  display: block;
  margin-top: 10px;
  color: var(--kb-accent);
  font-weight: 500;
  text-decoration: none;
}

.maintain-link:hover {
  color: var(--kb-accent-hover);
}

.main-row {
  margin-top: var(--kb-space-4);
}

.chart-title {
  color: var(--kb-text-primary);
  font-weight: 600;
  font-size: 15px;
}

.principle-card ul {
  margin: 0;
  padding-left: 18px;
  color: var(--kb-text-secondary);
  line-height: 1.9;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
}

.chart-grid h4 {
  margin: 0 0 14px;
  color: var(--kb-text-primary);
  font-size: 14px;
  font-weight: 600;
}

.bar-list {
  display: grid;
  gap: 14px;
}

.bar-item {
  display: grid;
  grid-template-columns: 76px 1fr 76px;
  align-items: center;
  gap: 10px;
}

.bar-label {
  color: var(--kb-text-secondary);
  font-size: 13px;
  text-align: right;
}

.bar-track {
  height: 18px;
  background: var(--kb-bg-hover);
  border-radius: 999px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  min-width: 4px;
  border-radius: 999px;
  transition: width 0.4s ease;
}

.bar-meta {
  display: flex;
  justify-content: space-between;
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.bar-count {
  color: var(--kb-text-primary);
  font-weight: 600;
}

.recent-card {
  margin-top: var(--kb-space-4);
}

.recent-card :deep(.el-card__header) {
  border-bottom: 1px solid var(--kb-border);
  padding: 14px 20px;
}

.recent-card :deep(.el-card__body) {
  padding: 16px 20px;
}

@media (max-width: 1280px) {
  .knowledge-map {
    min-height: auto;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    padding: 14px;
  }

  .map-lines {
    display: none;
  }

  .map-center,
  .map-node {
    position: static;
    width: auto;
    transform: none;
  }

  .evolve-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .responsibility-table {
    grid-template-columns: 88px 200px minmax(260px, 1fr);
  }

  .responsibility-table .table-head:nth-child(4),
  .responsibility-table .table-head:nth-child(5),
  .responsibility-table .table-head:nth-child(6),
  .responsibility-table .table-cell:nth-child(6n + 4),
  .responsibility-table .table-cell:nth-child(6n + 5),
  .responsibility-table .table-cell:nth-child(6n + 6) {
    display: none;
  }
}

@media (max-width: 820px) {
  .knowledge-map,
  .evolve-strip,
  .chart-grid {
    grid-template-columns: 1fr;
  }

  .section-head {
    display: block;
  }

  .head-actions {
    margin-top: 12px;
  }

  .responsibility-table {
    display: block;
  }

  .table-head {
    display: none;
  }

  .table-cell {
    min-height: auto;
    border-bottom: 0;
  }
}
</style>
