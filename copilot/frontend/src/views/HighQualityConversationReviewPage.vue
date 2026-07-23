<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getHighQualityReviewQueue,
  getHighQualityReviewScenario,
  saveHighQualityReview,
} from '../api/highQualityConversationReview'

const loading = ref(false)
const saving = ref(false)
const items = ref<any[]>([])
const selected = ref<any | null>(null)
const revisionHistory = ref<any[]>([])
const statusCounts = ref<any>({})
const authoritativeApprovalAllowed = ref(false)
const domains = ref<string[]>([])
const risks = ref<string[]>([])
const filters = reactive({ status: '', business_domain: '', risk_level: '' })
const form = reactive({
  gold_reply_revised: '', fact_correct: false, business_action_correct: false,
  safety_boundary_correct: false, human_tone_correct: false, notes: '', version: 0,
})

const statusText: Record<string, string> = {
  draft: '草稿', reviewed: '待主管复核', approved: '已批准', rejected: '已拒绝',
}
const riskText: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }
const roleText: Record<string, string> = { customer: '买家', agent: '客服', system: '系统' }
const claimStatusText: Record<string, string> = {
  supported: '应明确回答', unresolved: '应保留边界', conflicting: '证据冲突', prohibited: '禁止承诺',
}
const factTypeText: Record<string, string> = {
  material: '材质', dimensions: '尺寸', structure: '结构', installation: '安装',
  accessories: '配件', aftersales: '售后', logistics: '物流', promotion: '活动',
}
const progress = computed(() => `${statusCounts.value.approved || 0} / ${items.value.length || 26}`)
const allChecks = computed(() => form.fact_correct && form.business_action_correct && form.safety_boundary_correct && form.human_tone_correct)

function resetForm(scenario: any) {
  const label = scenario?.label
  form.gold_reply_revised = label?.gold_reply_revised || scenario?.gold_reply_original || ''
  form.fact_correct = Boolean(label?.fact_correct)
  form.business_action_correct = Boolean(label?.business_action_correct)
  form.safety_boundary_correct = Boolean(label?.safety_boundary_correct)
  form.human_tone_correct = Boolean(label?.human_tone_correct)
  form.notes = label?.notes || ''
  form.version = label?.version || 0
}

async function loadQueue(keepSelection = true) {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (filters.status) params.status = filters.status
    if (filters.business_domain) params.business_domain = filters.business_domain
    if (filters.risk_level) params.risk_level = filters.risk_level
    const { data } = await getHighQualityReviewQueue(params)
    items.value = data.items || []
    statusCounts.value = data.status_counts || {}
    authoritativeApprovalAllowed.value = Boolean(data.authoritative_approval_allowed)
    domains.value = data.business_domains || []
    risks.value = data.risk_levels || []
    const currentUid = keepSelection ? selected.value?.scenario_uid : ''
    const next = items.value.find((item) => item.scenario_uid === currentUid) || items.value[0]
    if (next) await selectScenario(next)
    else selected.value = null
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.error === 'review_dataset_not_configured' ? '尚未配置 v4.2 审核数据集。' : '审核队列加载失败。')
  } finally { loading.value = false }
}

async function selectScenario(item: any) {
  try {
    const { data } = await getHighQualityReviewScenario(item.scenario_uid)
    selected.value = data.scenario
    revisionHistory.value = data.revision_history || []
    resetForm(data.scenario)
  } catch { ElMessage.error('审核详情加载失败。') }
}

async function perform(action: 'draft' | 'submit' | 'approve' | 'reject') {
  if (!selected.value) return
  if (action === 'approve' && !allChecks.value) {
    ElMessage.warning('批准前需要确认四项人工判断。')
    return
  }
  if (action === 'reject' && !form.notes.trim()) {
    ElMessage.warning('拒绝时请填写简短原因。')
    return
  }
  if (action === 'approve') {
    await ElMessageBox.confirm('确认逐条批准当前对话吗？批准仅用于下一阶段评测，不会写入知识库。', '主管确认', { type: 'warning' })
  }
  saving.value = true
  try {
    const { data } = await saveHighQualityReview(selected.value.scenario_uid, action, { ...form })
    form.version = data.label.version
    selected.value.label = data.label
    ElMessage.success(action === 'approve' ? '当前对话已批准。' : action === 'reject' ? '当前对话已拒绝。' : action === 'submit' ? '已提交主管复核。' : '草稿已保存。')
    await loadQueue()
  } catch (error: any) {
    if (error?.response?.status === 409) {
      ElMessage.warning('该记录已被其他审核人修改，已为您刷新最新版本。')
      await selectScenario(selected.value)
    } else {
      const reason = error?.response?.data?.error
      ElMessage.error(reason === 'authoritative_supervisor_required' ? '只有通过 Cloudflare Access 登录的主管或管理员可以批准或拒绝。' : '保存失败，请检查填写内容。')
    }
  } finally { saving.value = false }
}

onMounted(() => loadQueue(false))
</script>

<template>
  <main class="review-page">
    <header class="page-header">
      <div>
        <h2>高质量长对话审核</h2>
        <p>逐条确认 v4.2 金牌客服回复。审核结果只用于评测，不进入 Agent、知识库或自动发送。</p>
      </div>
      <div class="progress" aria-label="审核进度">
        <strong>{{ progress }}</strong><span>已批准</span>
      </div>
    </header>

    <section class="toolbar" aria-label="审核筛选">
      <el-select v-model="filters.status" placeholder="全部状态" clearable @change="loadQueue(false)">
        <el-option v-for="(label, value) in statusText" :key="value" :label="label" :value="value" />
      </el-select>
      <el-select v-model="filters.business_domain" placeholder="全部业务域" clearable @change="loadQueue(false)">
        <el-option v-for="domain in domains" :key="domain" :label="domain" :value="domain" />
      </el-select>
      <el-select v-model="filters.risk_level" placeholder="全部风险等级" clearable @change="loadQueue(false)">
        <el-option v-for="risk in risks" :key="risk" :label="riskText[risk] || '待确认风险'" :value="risk" />
      </el-select>
      <div class="counts">
        <span>草稿 {{ statusCounts.draft || 0 }}</span><span>待复核 {{ statusCounts.reviewed || 0 }}</span>
        <span>已批准 {{ statusCounts.approved || 0 }}</span><span>已拒绝 {{ statusCounts.rejected || 0 }}</span>
      </div>
    </section>

    <el-alert v-if="!authoritativeApprovalAllowed" type="warning" :closable="false" title="当前会话可以查看和提交复核，但只有真实 Cloudflare Access 主管或管理员能够批准。" />

    <section class="workspace" v-loading="loading">
      <aside class="queue" aria-label="对话审核队列">
        <button v-for="item in items" :key="item.scenario_uid" type="button" :class="{ active: selected?.scenario_uid === item.scenario_uid }" @click="selectScenario(item)">
          <span class="queue-title"><strong>{{ item.scenario_title }}</strong><el-tag size="small" :type="item.label?.status === 'approved' ? 'success' : item.label?.status === 'rejected' ? 'danger' : 'info'">{{ statusText[item.label?.status || 'draft'] }}</el-tag></span>
          <span>{{ item.current_buyer_message }}</span>
          <small>{{ item.business_domain }} · {{ riskText[item.risk_level] || '风险待确认' }}</small>
        </button>
      </aside>

      <section v-if="selected" class="detail">
        <div class="metadata"><el-tag>{{ selected.business_domain }}</el-tag><el-tag type="info">{{ riskText[selected.risk_level] || '风险待确认' }}</el-tag><span>商品上下文：{{ selected.product_context.identity_present ? '已脱敏提供' : '未提供' }}</span></div>

        <h3>历史对话</h3>
        <div class="conversation">
          <div v-for="turn in selected.conversation_history" :key="turn.turn_uid" class="turn" :class="turn.role">
            <b>{{ roleText[turn.role] || '系统' }}</b><p>{{ turn.content }}</p>
          </div>
          <div class="turn customer current"><b>当前买家问题</b><p>{{ selected.current_buyer_message }}</p></div>
        </div>

        <h3>结构化商品上下文</h3>
        <div class="context-line"><span>商品：{{ selected.product_context.product_name || '未提供' }}</span><span>规格参考：{{ selected.product_context.variant_reference || '未提供' }}</span><span>订单上下文：{{ selected.order_context.order_context_present ? '已脱敏提供' : '未提供' }}</span></div>

        <h3>审核依据</h3>
        <div class="evidence-list">
          <div v-for="claim in selected.expected_claims" :key="claim.claim_uid"><el-tag size="small">{{ claimStatusText[claim.expected_status] || '需人工判断' }}</el-tag><span>{{ factTypeText[claim.claim_type] || '业务结论' }}：{{ (claim.required_answer_points || []).join('；') }}</span></div>
          <div v-if="!selected.expected_claims.length">当前没有结构化断言，请重点核对处理动作和安全边界。</div>
        </div>

        <h3>Codex 金牌客服草稿</h3>
        <el-input v-model="form.gold_reply_revised" type="textarea" :rows="5" resize="vertical" aria-label="修改后 Gold 回复" />
        <div class="original-reply"><b>原始草稿：</b>{{ selected.gold_reply_original }}</div>

        <h3>四项人工判断</h3>
        <div class="checks">
          <el-checkbox v-model="form.fact_correct">商品事实正确</el-checkbox>
          <el-checkbox v-model="form.business_action_correct">处理动作正确</el-checkbox>
          <el-checkbox v-model="form.safety_boundary_correct">安全边界正确</el-checkbox>
          <el-checkbox v-model="form.human_tone_correct">像真人金牌客服</el-checkbox>
        </div>
        <el-input v-model="form.notes" type="textarea" :rows="2" placeholder="审核备注；拒绝时必须填写原因" />

        <div class="actions">
          <el-button :loading="saving" @click="perform('draft')">保存草稿</el-button>
          <el-button :loading="saving" @click="perform('submit')">提交复核</el-button>
          <el-button type="success" :disabled="!authoritativeApprovalAllowed || !allChecks" :loading="saving" @click="perform('approve')">批准</el-button>
          <el-button type="danger" plain :disabled="!authoritativeApprovalAllowed" :loading="saving" @click="perform('reject')">拒绝</el-button>
        </div>

        <details v-if="revisionHistory.length" class="history"><summary>查看修订历史（{{ revisionHistory.length }}）</summary><div v-for="event in revisionHistory" :key="event.event_uid"><b>版本 {{ event.new_version }}</b><span>{{ statusText[event.to_status] || '已更新' }} · {{ event.timestamp }}</span><p>{{ event.gold_reply_revised }}</p></div></details>
      </section>
      <el-empty v-else description="当前筛选下没有待审核对话" />
    </section>
  </main>
</template>

<style scoped>
.review-page { max-width: 1500px; margin: 0 auto; padding: 20px; color: #1f2937; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }
.page-header h2 { margin: 0; font-size: 22px; }.page-header p { margin: 7px 0 16px; color: #667085; }
.progress { min-width: 96px; text-align: right; }.progress strong { display: block; font-size: 22px; }.progress span { color: #667085; font-size: 13px; }
.toolbar { display: flex; align-items: center; gap: 10px; padding: 12px 0; border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; }.toolbar :deep(.el-select) { width: 180px; }.counts { display: flex; flex-wrap: wrap; gap: 12px; margin-left: auto; color: #667085; font-size: 13px; }
.workspace { display: grid; grid-template-columns: minmax(280px, 340px) minmax(0, 1fr); min-height: 680px; margin-top: 14px; border-top: 1px solid #e5e7eb; }
.queue { overflow: auto; max-height: calc(100vh - 230px); border-right: 1px solid #e5e7eb; }.queue button { width: 100%; display: grid; gap: 6px; border: 0; border-bottom: 1px solid #eef0f3; background: #fff; padding: 12px; text-align: left; cursor: pointer; }.queue button:hover,.queue button.active { background: #f0f7ff; }.queue button > span:not(.queue-title) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.queue small { color: #667085; }.queue-title { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.detail { min-width: 0; padding: 0 18px 28px; }.detail h3 { margin: 18px 0 8px; font-size: 15px; }.metadata,.context-line { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; color: #667085; }.conversation { max-height: 360px; overflow: auto; background: #f8fafc; border: 1px solid #e5e7eb; padding: 12px; }.turn { max-width: 78%; margin: 8px 0; }.turn.agent { margin-left: auto; }.turn b { font-size: 12px; color: #667085; }.turn p { margin: 3px 0 0; padding: 8px 10px; background: #fff; border: 1px solid #e5e7eb; border-radius: 6px; line-height: 1.55; word-break: break-word; }.turn.current p { border-color: #409eff; background: #ecf5ff; }.evidence-list { display: grid; gap: 8px; }.evidence-list > div { display: flex; align-items: flex-start; gap: 8px; }.original-reply { margin-top: 8px; color: #667085; line-height: 1.6; }.checks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; margin-bottom: 12px; }.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }.history { margin-top: 20px; border-top: 1px solid #e5e7eb; padding-top: 12px; }.history > div { border-bottom: 1px solid #eef0f3; padding: 8px 0; }.history span { margin-left: 8px; color: #667085; }.history p { margin: 5px 0; white-space: pre-wrap; }
@media (max-width: 960px) { .review-page { padding: 14px; }.toolbar { align-items: stretch; flex-wrap: wrap; }.toolbar :deep(.el-select) { width: calc(50% - 5px); }.counts { width: 100%; margin-left: 0; }.workspace { grid-template-columns: 1fr; }.queue { max-height: 260px; border-right: 0; border-bottom: 1px solid #e5e7eb; }.detail { padding: 0 4px 24px; }.turn { max-width: 92%; } }
@media (max-width: 620px) { .page-header { display: grid; }.progress { text-align: left; }.toolbar :deep(.el-select) { width: 100%; }.checks { grid-template-columns: 1fr; } }
</style>
