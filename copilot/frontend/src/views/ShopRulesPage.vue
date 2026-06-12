<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

interface ActivityRule {
  id: string
  name: string
  type: string
  owner: string
  status: string
  timeRange: string
  scope: string
  ruleDetail: string
  customerReply: string
  forbiddenReply: string
  checkCycle: string
  updatedAt: string
}

const STORAGE_KEY = 'inhe_activity_rules_center_v2'

const rules = ref<ActivityRule[]>([])
const search = ref('')
const typeFilter = ref('')
const statusFilter = ref('')
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref('')

const defaultRules: ActivityRule[] = [
  {
    id: 'rule_coupon_001',
    name: '店铺优惠券使用规则',
    type: '优惠券',
    owner: '运营',
    status: 'active',
    timeRange: '按当前店铺后台配置',
    scope: '指定活动商品，以活动页展示为准',
    ruleDetail: '记录优惠券领取入口、使用门槛、是否可叠加、不可用商品和活动结束时间。',
    customerReply: '亲，优惠券一般需要先领取，再到结算页看是否满足使用条件。我帮您按当前活动规则确认一下。',
    forbiddenReply: '不能承诺所有商品都能用，也不能承诺一定可以叠加。',
    checkCycle: '活动开始前确认，活动期间每天检查一次。',
    updatedAt: '2026-06-11',
  },
  {
    id: 'rule_gift_001',
    name: '赠品发放规则',
    type: '赠品',
    owner: '运营',
    status: 'draft',
    timeRange: '待运营填写',
    scope: '参与赠品活动的商品或订单',
    ruleDetail: '记录赠品名称、数量、发放条件、缺赠品处理方式和活动页面截图位置。',
    customerReply: '亲，赠品需要看您下单时页面是否显示对应活动。我先帮您对一下订单和活动规则。',
    forbiddenReply: '未核实订单和活动页前，不直接承诺补发赠品。',
    checkCycle: '赠品规则变化当天更新。',
    updatedAt: '2026-06-11',
  },
  {
    id: 'rule_price_001',
    name: '价保处理规则',
    type: '价保',
    owner: '运营',
    status: 'draft',
    timeRange: '待运营填写',
    scope: '店铺活动期内符合条件的订单',
    ruleDetail: '记录是否支持价保、价保时间、差价计算方式、用户需要提供的截图或订单信息。',
    customerReply: '亲，价保我先帮您按活动规则和订单时间核实一下，符合的话会按店铺规则处理。',
    forbiddenReply: '不要先承诺一定退差价。',
    checkCycle: '大促活动前确认，价格变动当天复核。',
    updatedAt: '2026-06-11',
  },
]

const form = reactive<ActivityRule>({
  id: '',
  name: '',
  type: '优惠券',
  owner: '运营',
  status: 'draft',
  timeRange: '',
  scope: '',
  ruleDetail: '',
  customerReply: '',
  forbiddenReply: '',
  checkCycle: '',
  updatedAt: '',
})

const filteredRules = computed(() => {
  const keyword = search.value.trim()
  return rules.value.filter((rule) => {
    const matchesSearch = !keyword || [
      rule.name,
      rule.type,
      rule.scope,
      rule.ruleDetail,
      rule.customerReply,
    ].some((item) => item.includes(keyword))
    const matchesType = !typeFilter.value || rule.type === typeFilter.value
    const matchesStatus = !statusFilter.value || rule.status === statusFilter.value
    return matchesSearch && matchesType && matchesStatus
  })
})

const stats = computed(() => [
  { label: '规则总数', value: rules.value.length, color: '#409eff' },
  { label: '生效中', value: rules.value.filter((rule) => rule.status === 'active').length, color: '#67c23a' },
  { label: '待补全', value: rules.value.filter((rule) => rule.status === 'draft').length, color: '#e6a23c' },
  { label: '已暂停', value: rules.value.filter((rule) => rule.status === 'paused').length, color: '#909399' },
])

function today() {
  return new Date().toISOString().slice(0, 10)
}

function persistRules() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rules.value))
}

function loadRules() {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) {
    rules.value = defaultRules.map((rule) => ({ ...rule }))
    persistRules()
    return
  }
  try {
    const parsed = JSON.parse(raw)
    rules.value = Array.isArray(parsed) ? parsed : defaultRules.map((rule) => ({ ...rule }))
  } catch {
    rules.value = defaultRules.map((rule) => ({ ...rule }))
  }
}

function resetForm() {
  Object.assign(form, {
    id: '',
    name: '',
    type: '优惠券',
    owner: '运营',
    status: 'draft',
    timeRange: '',
    scope: '',
    ruleDetail: '',
    customerReply: '',
    forbiddenReply: '',
    checkCycle: '',
    updatedAt: today(),
  })
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = ''
  resetForm()
  dialogVisible.value = true
}

function openEdit(rule: ActivityRule) {
  dialogMode.value = 'edit'
  editingId.value = rule.id
  Object.assign(form, { ...rule })
  dialogVisible.value = true
}

function saveRule() {
  if (!form.name.trim() || !form.type.trim()) {
    ElMessage.warning('请填写规则名称和规则类型')
    return
  }
  const payload = { ...form, updatedAt: today() }
  if (dialogMode.value === 'create') {
    payload.id = `rule_${Date.now()}`
    rules.value.unshift(payload)
  } else {
    const index = rules.value.findIndex((rule) => rule.id === editingId.value)
    if (index >= 0) rules.value[index] = payload
  }
  persistRules()
  dialogVisible.value = false
  ElMessage.success('已保存活动规则')
}

async function removeRule(rule: ActivityRule) {
  try {
    await ElMessageBox.confirm(`确认删除「${rule.name}」吗？`, '删除活动规则')
  } catch {
    return
  }
  rules.value = rules.value.filter((item) => item.id !== rule.id)
  persistRules()
  ElMessage.success('已删除')
}

function statusType(status: string) {
  if (status === 'active') return 'success'
  if (status === 'paused') return 'info'
  return 'warning'
}

function statusLabel(status: string) {
  return ({ active: '生效中', draft: '待补全', paused: '已暂停' } as Record<string, string>)[status] || status
}

onMounted(loadRules)
</script>

<template>
  <div class="activity-rules-page">
    <div class="page-head">
      <div>
        <h2>活动规则中心</h2>
        <p>运营在这里维护活动、优惠券、赠品、价保、发票和店铺页面口径，客服按这里的规则回复客户。</p>
      </div>
      <div class="actions">
        <el-button type="primary" @click="openCreate">新增规则</el-button>
      </div>
    </div>

    <el-row :gutter="10" class="summary-row">
      <el-col v-for="item in stats" :key="item.label" :span="6">
        <div class="summary-card" :style="{ borderTopColor: item.color }">
          <div class="card-value" :style="{ color: item.color }">{{ item.value }}</div>
          <div class="card-label">{{ item.label }}</div>
        </div>
      </el-col>
    </el-row>

    <div class="filter-bar">
      <el-input v-model="search" placeholder="搜索活动/优惠券/赠品/回复口径" clearable size="small" style="width:260px" />
      <el-select v-model="typeFilter" placeholder="规则类型" clearable size="small" style="width:120px">
        <el-option label="优惠券" value="优惠券" />
        <el-option label="赠品" value="赠品" />
        <el-option label="价保" value="价保" />
        <el-option label="发票" value="发票" />
        <el-option label="页面口径" value="页面口径" />
      </el-select>
      <el-select v-model="statusFilter" placeholder="状态" clearable size="small" style="width:110px">
        <el-option label="生效中" value="active" />
        <el-option label="待补全" value="draft" />
        <el-option label="已暂停" value="paused" />
      </el-select>
      <div class="filter-spacer"></div>
      <span class="count-text">共 {{ filteredRules.length }} 条</span>
    </div>

    <el-table :data="filteredRules" stripe size="small" class="rules-table">
      <el-table-column label="活动/规则" min-width="180">
        <template #default="{ row }">
          <div class="rule-name">{{ row.name }}</div>
          <div class="rule-sub">{{ row.timeRange || '未填写活动时间' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="类型" prop="type" width="90" />
      <el-table-column label="适用范围" prop="scope" min-width="170" show-overflow-tooltip />
      <el-table-column label="规则内容" prop="ruleDetail" min-width="230" show-overflow-tooltip />
      <el-table-column label="客服回复口径" prop="customerReply" min-width="260" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status) as any" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="负责人" prop="owner" width="100" />
      <el-table-column label="更新" prop="updatedAt" width="100" />
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" size="small" @click="removeRule(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新增活动规则' : '编辑活动规则'" width="72%" destroy-on-close>
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="活动/规则名称">
              <el-input v-model="form.name" placeholder="例如：618 满减优惠券" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="规则类型">
              <el-select v-model="form.type" style="width:100%">
                <el-option label="优惠券" value="优惠券" />
                <el-option label="赠品" value="赠品" />
                <el-option label="价保" value="价保" />
                <el-option label="发票" value="发票" />
                <el-option label="页面口径" value="页面口径" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width:100%">
                <el-option label="生效中" value="active" />
                <el-option label="待补全" value="draft" />
                <el-option label="已暂停" value="paused" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="运营负责人">
              <el-input v-model="form.owner" />
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="活动时间/生效范围">
              <el-input v-model="form.timeRange" placeholder="例如：2026-06-01 至 2026-06-20 / 指定商品可用" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="适用范围">
              <el-input v-model="form.scope" placeholder="例如：全店通用 / 指定商品 / 指定店铺 / 满指定金额可用" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="规则内容">
              <el-input v-model="form.ruleDetail" type="textarea" :rows="5" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="不能这样承诺">
              <el-input v-model="form.forbiddenReply" type="textarea" :rows="5" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="客服回复口径">
              <el-input v-model="form.customerReply" type="textarea" :rows="5" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="多久检查一次">
              <el-input v-model="form.checkCycle" placeholder="例如：活动开始前确认，活动期间每天检查一次。" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.activity-rules-page { padding: 16px; }
.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; background: #fff; border-radius: 8px; padding: 18px; box-shadow: 0 1px 4px rgba(0,0,0,.06); margin-bottom: 12px; }
.page-head h2 { margin: 0; color: #0f172a; font-size: 20px; }
.page-head p { margin: 8px 0 0; color: #64748b; }
.actions { display: flex; gap: 8px; flex-shrink: 0; }
.summary-row { margin-bottom: 12px; }
.summary-card { background: #fff; border-radius: 8px; padding: 14px; border-top: 3px solid; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.card-value { font-size: 22px; font-weight: 800; }
.card-label { color: #909399; font-size: 12px; margin-top: 2px; }
.filter-bar { display: flex; align-items: center; gap: 8px; background: #fff; border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.filter-spacer { flex: 1; }
.count-text { color: #909399; font-size: 13px; }
.rules-table { width: 100%; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.rule-name { color: #409eff; font-weight: 700; }
.rule-sub { color: #909399; font-size: 12px; margin-top: 2px; }
@media (max-width: 900px) {
  .page-head { display: block; }
  .actions { margin-top: 12px; }
  .filter-bar { flex-wrap: wrap; }
}
</style>
