<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSOPRiskTree } from '../api/qa'
import { getSOPList, getSOP, createSOP, updateSOP, publishSOP, deleteSOP } from '../api/sop'
import RiskBadge from '../components/common/RiskBadge.vue'
import StatusTag from '../components/common/StatusTag.vue'

const loading = ref(false)
const sops = ref<any[]>([])
const total = ref(0)
const navTree = ref<any[]>([])
const navLoading = ref(false)
const drawerVisible = ref(false)
const currentSOP = ref<any>(null)
const formDrawerVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const sopForm = reactive<any>({
  scenario: '',
  scenario_code: '',
  category_l1: '',
  owner: '',
  risk_level: 'medium',
  status: 'draft',
  keywordsText: '',
  stepsText: '',
  forbiddenText: '',
  escalation_condition: '',
  escalation_target: '',
  response_template: '',
})
const selectedScene = ref('')

const filters = reactive({ risk_level: '', status: '', search: '', page: 1, page_size: 20 })

// ─── Navigation ───
async function fetchNavTree() {
  navLoading.value = true
  try { const { data } = await getSOPRiskTree(); navTree.value = data } catch { navTree.value = [] } finally { navLoading.value = false }
}

function onNavClick(data: any) {
  if (data.sop_id) {
    openDetail(data.sop_id)
  } else {
    selectedScene.value = data.label
    filters.page = 1
    fetchSOPs()
  }
}

// ─── Data ───
async function fetchSOPs() {
  loading.value = true
  try {
    const params: Record<string, any> = { limit: filters.page_size, offset: (filters.page - 1) * filters.page_size }
    if (filters.risk_level) params.risk_level = filters.risk_level
    if (filters.status) params.status = filters.status
    if (filters.search) params.search = filters.search
    const { data } = await getSOPList(params)
    let items = data.items || []
    // Filter by selected scene
    if (selectedScene.value) {
      items = items.filter((s: any) => categorizeScene(s.scenario) === selectedScene.value)
    }
    sops.value = items; total.value = data.total
  } catch { ElMessage.error('加载 SOP 失败') } finally { loading.value = false }
}

function categorizeScene(scenario: string): string {
  if (!scenario) return '其他'
  if (scenario.includes('投诉') || scenario.includes('差评') || scenario.includes('12315') || scenario.includes('平台')) return '投诉/差评'
  if (scenario.includes('赔偿') || scenario.includes('退款') || scenario.includes('补偿')) return '赔偿/退款'
  if (scenario.includes('受伤') || scenario.includes('夹伤') || scenario.includes('倒塌') || scenario.includes('坍塌')) return '安全事故'
  if (scenario.includes('质量') || scenario.includes('破损') || scenario.includes('缺件')) return '质量问题'
  return '平台规则'
}

async function openDetail(id: number) {
  drawerVisible.value = true
  try { const { data } = await getSOP(id); currentSOP.value = data } catch { ElMessage.error('加载详情失败') }
}

function resetSOPForm() {
  Object.assign(sopForm, {
    scenario: '',
    scenario_code: '',
    category_l1: selectedScene.value || '',
    owner: '',
    risk_level: 'medium',
    status: 'draft',
    keywordsText: '',
    stepsText: '',
    forbiddenText: '',
    escalation_condition: '',
    escalation_target: '',
    response_template: '',
  })
}

function textToList(text: string) {
  return String(text || '').split('\n').map((i) => i.trim()).filter(Boolean)
}

function fillSOPForm(sop: any) {
  Object.assign(sopForm, {
    scenario: sop.scenario || '',
    scenario_code: sop.scenario_code || '',
    category_l1: sop.category_l1 || '',
    owner: sop.owner || '',
    risk_level: sop.risk_level || 'medium',
    status: sop.status || 'draft',
    keywordsText: (sop.keywords || []).join('\n'),
    stepsText: (sop.steps || []).map((s: any) => typeof s === 'string' ? s : s.action).join('\n'),
    forbiddenText: (sop.forbidden_actions || []).join('\n'),
    escalation_condition: sop.escalation_condition || '',
    escalation_target: sop.escalation_target || '',
    response_template: sop.response_template || '',
  })
}

function buildSOPPayload() {
  return {
    scenario: sopForm.scenario,
    scenario_code: sopForm.scenario_code,
    category_l1: sopForm.category_l1,
    owner: sopForm.owner,
    risk_level: sopForm.risk_level,
    status: sopForm.status,
    keywords: textToList(sopForm.keywordsText),
    steps: textToList(sopForm.stepsText).map((action) => ({ action })),
    forbidden_actions: textToList(sopForm.forbiddenText),
    escalation_condition: sopForm.escalation_condition,
    escalation_target: sopForm.escalation_target,
    response_template: sopForm.response_template,
  }
}

function openCreateSOP() {
  formMode.value = 'create'
  resetSOPForm()
  formDrawerVisible.value = true
}

function openEditSOP() {
  if (!currentSOP.value) return
  formMode.value = 'edit'
  fillSOPForm(currentSOP.value)
  formDrawerVisible.value = true
}

async function saveSOPForm() {
  if (!sopForm.scenario || !sopForm.scenario_code) {
    ElMessage.warning('请填写场景名称和 SOP 编号')
    return
  }
  try {
    const payload = buildSOPPayload()
    if (formMode.value === 'create') {
      const { data } = await createSOP(payload)
      ElMessage.success('新增 SOP 成功')
      formDrawerVisible.value = false
      await fetchSOPs(); await fetchNavTree()
      openDetail(data.id)
    } else {
      const { data } = await updateSOP(currentSOP.value.id, payload)
      ElMessage.success('已保存 SOP')
      formDrawerVisible.value = false
      currentSOP.value = data
      await fetchSOPs(); await fetchNavTree()
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  }
}

async function handlePublishSOP() {
  if (!currentSOP.value) return
  try {
    const { data } = await publishSOP(currentSOP.value.id)
    currentSOP.value = data
    ElMessage.success('已发布')
    fetchSOPs(); fetchNavTree()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '发布失败')
  }
}

async function handleDeleteSOP() {
  if (!currentSOP.value) return
  try { await ElMessageBox.confirm('确认删除这个 SOP？删除后会归档，不再出现在列表中。', '删除 SOP') } catch { return }
  try {
    await deleteSOP(currentSOP.value.id)
    ElMessage.success('已删除')
    drawerVisible.value = false
    fetchSOPs(); fetchNavTree()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '删除失败')
  }
}

function resetFilters() {
  Object.assign(filters, { risk_level: '', status: '', search: '', page: 1 })
  selectedScene.value = ''
  fetchSOPs()
}

function copyText(text: string) {
  navigator.clipboard?.writeText(text); ElMessage.success('已复制')
}

onMounted(() => { fetchNavTree(); fetchSOPs() })
</script>

<template>
  <div class="sop-page">
    <el-row :gutter="16" class="main-row">
      <!-- Left: Risk Scene Navigation -->
      <el-col :span="5">
        <div class="nav-panel">
          <div class="nav-header"><span style="font-weight:600;font-size:14px">风险场景</span><el-button v-if="selectedScene" link size="small" @click="resetFilters">清除</el-button></div>
          <el-tree :data="navTree" :props="{ children: 'children', label: 'label' }" node-key="label" default-expand-all highlight-current v-loading="navLoading" @node-click="onNavClick">
            <template #default="{ data }">
              <div class="nav-node">
                <span class="nav-label">{{ data.label }}</span>
                <span class="nav-stats">
                  <span class="nav-count">SOP {{ data.count || data.qa_count || 0 }}</span>
                  <el-tag v-if="data.qa_count && data.count" size="small" type="info" class="nav-tag">QA {{ data.qa_count }}</el-tag>
                </span>
              </div>
            </template>
          </el-tree>
        </div>
      </el-col>

      <!-- Right: SOP Cards -->
      <el-col :span="19">
        <div class="filter-bar">
          <el-input v-model="filters.search" placeholder="搜索场景/关键词" clearable size="small" style="width:200px" @clear="fetchSOPs" @keyup.enter="fetchSOPs" />
          <el-select v-model="filters.risk_level" placeholder="风险等级" clearable size="small" @change="fetchSOPs" style="width:100px">
            <el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="极高" value="critical" />
          </el-select>
          <el-button size="small" @click="resetFilters">重置</el-button>
          <div style="flex:1"></div>
          <span v-if="selectedScene" style="font-size:13px;color:#409eff">筛选: {{ selectedScene }}</span>
          <el-button size="small" type="success" @click="openCreateSOP">新增 SOP</el-button>
        </div>

        <div v-loading="loading" class="sop-grid">
          <el-card v-for="sop in sops" :key="sop.id" shadow="hover" class="sop-card" @click="openDetail(sop.id)">
            <div class="sc-header">
              <div>
                <span class="sc-code">{{ sop.scenario_code }}</span>
                <span class="sc-name">{{ sop.scenario }}</span>
              </div>
              <RiskBadge :level="sop.risk_level" />
            </div>
            <div class="sc-keywords">
              <el-tag v-for="k in (sop.keywords||[]).slice(0,4)" :key="k" size="small" style="margin:2px">{{ k }}</el-tag>
              <el-tag v-if="(sop.keywords||[]).length > 4" size="small" type="info">+{{ (sop.keywords||[]).length - 4 }}</el-tag>
            </div>
            <div class="sc-steps" v-if="sop.steps?.length">
              <div v-for="(step, i) in sop.steps.slice(0,3)" :key="i" class="sc-step">
                <span class="step-num">{{ Number(i)+1 }}</span>
                <span>{{ typeof step === 'string' ? step : step.action }}</span>
              </div>
              <div v-if="sop.steps.length > 3" class="sc-more">+{{ sop.steps.length - 3 }} 步</div>
            </div>
            <div class="sc-forbidden" v-if="sop.forbidden_actions?.length">
              <el-tag type="danger" size="small" effect="dark">禁止 {{ sop.forbidden_actions.length }} 项</el-tag>
            </div>
            <div class="sc-footer">
              <StatusTag :status="sop.status" />
              <span class="sc-time">{{ sop.updated_at?.slice(0, 10) }}</span>
            </div>
          </el-card>
          <el-empty v-if="!loading && !sops.length" description="暂无 SOP" />
        </div>
      </el-col>
    </el-row>

    <!-- Detail Drawer -->
    <el-drawer v-model="drawerVisible" :title="currentSOP?.scenario || 'SOP 详情'" size="65%" destroy-on-close>
      <template v-if="currentSOP">
        <div class="drawer-actions">
          <el-button type="primary" @click="openEditSOP">编辑</el-button>
          <el-button type="success" @click="handlePublishSOP">发布</el-button>
          <el-button type="danger" @click="handleDeleteSOP">删除</el-button>
        </div>

        <el-descriptions :column="2" border size="small" style="margin-bottom:16px">
          <el-descriptions-item label="SOP 编号">{{ currentSOP.scenario_code }}</el-descriptions-item>
          <el-descriptions-item label="风险等级"><RiskBadge :level="currentSOP.risk_level" /></el-descriptions-item>
          <el-descriptions-item label="场景" :span="2">{{ currentSOP.scenario }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ currentSOP.owner || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态"><StatusTag :status="currentSOP.status" /></el-descriptions-item>
        </el-descriptions>

        <h4>触发关键词</h4>
        <div style="margin-bottom:16px">
          <el-tag v-for="k in currentSOP.keywords||[]" :key="k" style="margin:2px">{{ k }}</el-tag>
        </div>

        <h4>处理步骤</h4>
        <el-steps direction="vertical" :active="currentSOP.steps?.length" finish-status="success" style="margin-bottom:16px">
          <el-step v-for="(step, i) in currentSOP.steps||[]" :key="i" :title="`步骤 ${Number(i)+1}`" :description="typeof step === 'string' ? step : step.action" />
        </el-steps>

        <h4>升级规则</h4>
        <div style="margin-bottom:16px;color:#606266">{{ currentSOP.escalation_condition || '-' }}</div>

        <h4>禁止行为</h4>
        <el-alert v-for="f in currentSOP.forbidden_actions||[]" :key="f" :title="f" type="error" show-icon :closable="false" style="margin-bottom:6px" />

        <h4>标准回复模板</h4>
        <el-card shadow="never" style="margin-bottom:16px">
          <pre style="white-space:pre-wrap;margin:0">{{ currentSOP.response_template }}</pre>
          <el-button size="small" type="primary" link style="margin-top:8px" @click="copyText(currentSOP.response_template)">复制</el-button>
        </el-card>

        <h4>Agent 动作</h4>
        <div style="margin-bottom:16px">
          <el-tag v-if="currentSOP.risk_level==='critical'" type="danger" effect="dark">禁止自动回复</el-tag>
          <el-tag v-else-if="currentSOP.risk_level==='high'" type="danger">客服确认</el-tag>
          <el-tag v-else-if="currentSOP.risk_level==='medium'" type="warning">主管审核</el-tag>
          <el-tag v-else type="success">自动回复</el-tag>
        </div>
      </template>
    </el-drawer>

    <el-drawer v-model="formDrawerVisible" :title="formMode === 'create' ? '新增售后 SOP' : '编辑售后 SOP'" size="70%" destroy-on-close>
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="场景名称"><el-input v-model="sopForm.scenario" placeholder="例如：少件/补配件处理" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="SOP 编号"><el-input v-model="sopForm.scenario_code" placeholder="例如：AFTERSALE-MISSING-PARTS" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="分类"><el-input v-model="sopForm.category_l1" placeholder="例如：少件补发" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="负责人"><el-input v-model="sopForm.owner" /></el-form-item></el-col>
          <el-col :span="4">
            <el-form-item label="风险等级">
              <el-select v-model="sopForm.risk_level" style="width:100%">
                <el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="极高" value="critical" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="状态">
              <el-select v-model="sopForm.status" style="width:100%">
                <el-option label="草稿" value="draft" /><el-option label="待审核" value="pending_review" /><el-option label="已发布" value="published" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8"><el-form-item label="触发关键词（一行一个）"><el-input v-model="sopForm.keywordsText" type="textarea" :rows="8" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="处理步骤（一行一步）"><el-input v-model="sopForm.stepsText" type="textarea" :rows="8" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="禁止行为（一行一个）"><el-input v-model="sopForm.forbiddenText" type="textarea" :rows="8" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="升级条件"><el-input v-model="sopForm.escalation_condition" type="textarea" :rows="3" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="升级对象"><el-input v-model="sopForm.escalation_target" placeholder="例如：客服主管/仓配/质检" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="标准回复模板"><el-input v-model="sopForm.response_template" type="textarea" :rows="6" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="formDrawerVisible=false">取消</el-button>
        <el-button type="primary" @click="saveSOPForm">保存</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.sop-page { padding: 16px; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 12px; }
.main-row { min-height: calc(100vh - 120px); }
.nav-panel { background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); max-height: calc(100vh - 120px); overflow-y: auto; }
.nav-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.nav-node { display: flex; align-items: center; justify-content: space-between; width: 100%; font-size: 13px; }
.nav-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nav-stats { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.nav-count { color: #909399; font-size: 11px; }
.nav-tag { transform: scale(0.75); }
.filter-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; background: #fff; padding: 10px 12px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.sop-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.sop-card { cursor: pointer; transition: all .2s; }
.sop-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.12); }
.sc-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
.sc-code { font-size: 11px; color: #909399; margin-right: 8px; }
.sc-name { font-weight: 700; font-size: 15px; color: #303133; }
.sc-keywords { margin-bottom: 8px; }
.sc-steps { background: #f5f7fa; border-radius: 4px; padding: 8px 12px; margin-bottom: 8px; }
.sc-step { display: flex; align-items: baseline; margin-bottom: 4px; font-size: 13px; color: #606266; }
.step-num { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: #409eff; color: #fff; font-size: 11px; margin-right: 8px; flex-shrink: 0; }
.sc-more { font-size: 12px; color: #909399; }
.sc-forbidden { margin-bottom: 8px; }
.sc-footer { display: flex; justify-content: space-between; align-items: center; }
.sc-time { font-size: 12px; color: #909399; }
</style>
