<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  applyRealAccuracyProposals,
  getRealAccuracyCases,
  saveRealAccuracyLabel,
  submitRealAccuracyBatchForReview,
  type AccuracyClaim,
} from '../api/realAccuracy'

const loading = ref(false)
const saving = ref(false)
const cases = ref<any[]>([])
const groups = ref<any[]>([])
const selected = ref<any | null>(null)
const selectedCaseUids = ref<string[]>([])
const strategyFilter = ref('')
const error = ref('')
const form = reactive<{ claims: AccuracyClaim[]; targetTurnUids: string[]; reviewStatus: 'draft' | 'reviewed' | 'approved'; version: number }>({
  claims: [], targetTurnUids: [], reviewStatus: 'draft', version: 0,
})

const statusText: Record<string, string> = {
  claim_label_pending: '待拆分断言', claim_accuracy_scorable: '可计入准确率',
  safety_scorable: '仅安全评估', context_gap: '上下文缺失', media_only: '仅图片或链接',
  privacy_review_required: '隐私待复核', invalid: '无效样本', label_gap: '待补标签',
  role_unresolved: '角色未解析', conversation_truncated: '对话过长待复核',
}
const proposalText: Record<string, string> = {
  ai_proposed: 'AI 建议', source_reviewed_candidate: '已审核来源候选',
  policy_validated: '策略已校验', supervisor_approved: '主管已批准', rejected: '已拒绝',
}
const claimKindText: Record<string, string> = {
  factual_claim: '商品事实', product_fact: '商品事实', service_action: '客服动作', tool_action: '工具核对',
  unresolved_claim: '待确认结论', prohibited: '禁止断言', delivery_constraint: '发送条件',
  context_requirement: '上下文要求', handoff: '人工跟进',
}
const canApprove = computed(() => form.claims.length > 0 && form.targetTurnUids.length > 0)
const activeGroup = computed(() => groups.value.find((item) => item.id === strategyFilter.value))
const batchReadyIds = computed(() => selectedCaseUids.value.filter((uid) => {
  const item = cases.value.find((row) => row.case_uid === uid)
  return item?.label?.review_status === 'draft' && item?.label?.label?.target_turn_uids?.length
}))

function split(value: string) { return value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean) }
function join(value: string[] | undefined) { return (value || []).join('，') }
function evidenceSummary(item: any) {
  const count = item?.formal_evidence_summary?.length || 0
  return count ? `已关联 ${count} 条正式证据` : '未发现可直接支持的正式商品事实'
}
function resetForm(item: any) {
  const saved = item.label
  form.claims = saved?.label?.claims ? JSON.parse(JSON.stringify(saved.label.claims)) : JSON.parse(JSON.stringify(item.candidate_claims || []))
  form.targetTurnUids = saved?.label?.target_turn_uids ? [...saved.label.target_turn_uids] : []
  form.reviewStatus = saved?.review_status || 'draft'
  form.version = saved?.optimistic_lock_version || 0
}
function select(item: any) {
  selected.value = item
  resetForm(item)
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const { data } = await getRealAccuracyCases(strategyFilter.value ? { strategy_group: strategyFilter.value } : {})
    cases.value = data.items || []
    groups.value = data.strategy_groups || []
    selectedCaseUids.value = selectedCaseUids.value.filter((uid) => cases.value.some((item) => item.case_uid === uid))
    if (cases.value.length) select(cases.value[0]); else selected.value = null
  } catch (e: any) {
    error.value = e?.response?.data?.error === 'gold_set_not_configured'
      ? '当前没有可用的脱敏 Gold Set，暂时不能开始人工标注。'
      : '加载评测样本失败。'
  } finally { loading.value = false }
}
async function save(status: 'draft' | 'reviewed' | 'approved') {
  if (!selected.value) return
  saving.value = true
  try {
    const { data } = await saveRealAccuracyLabel(selected.value.case_uid, {
      claims: form.claims, target_turn_uids: form.targetTurnUids,
      review_status: status, optimistic_lock_version: form.version,
    })
    form.version = data.label.optimistic_lock_version
    form.reviewStatus = data.label.review_status
    selected.value.label = data.label
    ElMessage.success(status === 'approved' ? '已由主管批准，可计入准确率。' : status === 'reviewed' ? '已提交复核。' : '草稿已保存。')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally { saving.value = false }
}
async function applyProposals() {
  const caseUids = selectedCaseUids.value.length ? selectedCaseUids.value : (selected.value ? [selected.value.case_uid] : [])
  if (!caseUids.length) return
  saving.value = true
  try {
    const { data } = await applyRealAccuracyProposals(caseUids)
    ElMessage.success(`已创建 ${data.created_draft_count || 0} 条草稿；不会自动批准。`)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '创建草稿失败')
  } finally { saving.value = false }
}
async function submitBatch() {
  if (!strategyFilter.value || !batchReadyIds.value.length) return
  saving.value = true
  try {
    const { data } = await submitRealAccuracyBatchForReview(strategyFilter.value, batchReadyIds.value)
    ElMessage.success(`已提交 ${data.reviewed_count || 0} 条复核；主管仍需逐条批准。`)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '批量提交失败')
  } finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <main class="page-container accuracy-workbench">
    <header class="page-header">
      <div><h2>真实准确率人工标注</h2><p>只处理脱敏评测样本。策略建议和草稿不会写入商品知识库，也不会影响客服回复。</p></div>
      <div class="header-controls">
        <el-select v-model="strategyFilter" placeholder="全部处理策略" clearable @change="load">
          <el-option v-for="group in groups" :key="group.id" :label="group.label" :value="group.id" />
        </el-select>
        <el-button :disabled="!selected && !selectedCaseUids.length" :loading="saving" @click="applyProposals">生成草稿</el-button>
        <el-button type="primary" :disabled="!strategyFilter || !batchReadyIds.length" :loading="saving" @click="submitBatch">批量提交复核</el-button>
      </div>
    </header>
    <el-alert v-if="activeGroup" type="info" :closable="false" :title="activeGroup.label" :description="activeGroup.description" />
    <el-alert v-if="error" type="warning" :closable="false" :title="error" />
    <section v-else class="workbench-grid" v-loading="loading">
      <aside class="case-list" aria-label="评测样本列表">
        <label v-for="item in cases" :key="item.case_uid" class="case-row" :class="{ active: selected?.case_uid === item.case_uid }">
          <el-checkbox v-model="selectedCaseUids" :value="item.case_uid" @click.stop />
          <button type="button" @click="select(item)">
            <strong>{{ item.strategy?.label || statusText[item.classification] || '待处理' }}</strong>
            <span>{{ item.customer_message }}</span>
            <small>{{ proposalText[item.proposal_status] || '待处理' }} · {{ evidenceSummary(item) }}</small>
          </button>
        </label>
      </aside>
      <section v-if="selected" class="case-detail">
        <el-alert v-if="selected.privacy_review_required" type="error" :closable="false" title="该样本仍需隐私复核，不能批准标签。" />
        <el-alert v-else-if="selected.exclusion_reason" type="warning" :closable="false" :title="`暂不进入批量审核：${selected.exclusion_reason}`" />
        <div class="metadata-line"><el-tag>{{ selected.strategy?.label }}</el-tag><el-tag type="info">{{ proposalText[selected.proposal_status] }}</el-tag><span>{{ evidenceSummary(selected) }}</span></div>
        <h3>当前买家问题</h3><p>{{ selected.customer_message }}</p>
        <h3>必要上下文窗口</h3>
        <el-alert type="info" :closable="false" :title="selected.target_recommendation?.requires_confirmation ? '系统仅推荐了可能对应的买家消息，请人工确认后勾选。' : '已使用此前人工选择的买家消息。'" />
        <div class="turns">
          <label v-for="turn in selected.conversation_window?.turns || []" :key="turn.turn_uid" class="turn-row" :class="{ target: form.targetTurnUids.includes(turn.turn_uid) }">
            <el-checkbox v-if="turn.speaker_role === 'BUYER'" v-model="form.targetTurnUids" :value="turn.turn_uid" />
            <span v-else class="turn-spacer" />
            <b>{{ turn.speaker_role === 'BUYER' ? '买家' : turn.speaker_role === 'AGENT' ? '客服' : '系统' }}：</b>
            <span>{{ turn.text }}</span>
          </label>
        </div>
        <small v-if="selected.conversation_window?.truncated">仅展示与当前审核目标相邻的必要窗口，共 {{ selected.conversation_window.total_turn_count }} 条回合。</small>
        <h3>已审核回复参考</h3><p>{{ selected.reference_label.reference_text || '暂无已审核回复参考。' }}</p>
        <h3>待审核原子断言</h3>
        <article v-for="(claim, index) in form.claims" :key="claim.claim_uid" class="claim-form">
          <div class="claim-heading"><strong>{{ claimKindText[claim.claim_kind] || '其他断言' }}</strong><el-tag size="small">{{ claim.expected_status === 'supported' ? '有证据支持' : claim.expected_status === 'unresolved' ? '无法确认' : claim.expected_status === 'conflicting' ? '证据冲突' : '禁止断言' }}</el-tag></div>
          <el-row :gutter="12"><el-col :span="12"><el-input v-model="claim.attribute_key" placeholder="审核属性" /></el-col><el-col :span="12"><el-input :model-value="join(claim.required_action_points)" @update:model-value="claim.required_action_points = split($event)" placeholder="需要完成的客服动作，用逗号分隔" /></el-col></el-row>
          <el-row :gutter="12"><el-col :span="12"><el-input :model-value="join(claim.forbidden_claims)" @update:model-value="claim.forbidden_claims = split($event)" placeholder="不能承诺的内容，用逗号分隔" /></el-col><el-col :span="12"><el-input :model-value="join(claim.supporting_evidence_uids)" @update:model-value="claim.supporting_evidence_uids = split($event)" placeholder="正式证据 UID（支持型商品事实必填）" /></el-col></el-row>
          <el-checkbox v-model="claim.must_handoff">必须人工复核</el-checkbox><el-checkbox v-model="claim.partial_answer_allowed">允许保留已支持部分</el-checkbox><el-button link type="danger" @click="form.claims.splice(index, 1)">删除</el-button>
        </article>
        <div class="actions"><el-button :loading="saving" @click="save('draft')">保存草稿</el-button><el-button :disabled="!canApprove" :loading="saving" @click="save('reviewed')">提交复核</el-button><el-button type="primary" :disabled="!canApprove || selected.privacy_review_required" :loading="saving" @click="save('approved')">主管逐条批准</el-button></div>
      </section>
    </section>
  </main>
</template>

<style scoped>
.accuracy-workbench { max-width: 1440px; margin: 0 auto; padding: 24px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }.page-header h2 { margin: 0; font-size: 22px; }.page-header p { color: #667085; margin: 8px 0 20px; }.header-controls { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.workbench-grid { display: grid; grid-template-columns: minmax(300px, 360px) minmax(0, 1fr); gap: 20px; min-height: 600px; margin-top: 16px; }.case-list { border-right: 1px solid #e4e7ed; overflow: auto; }.case-row { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 6px; align-items: start; border-bottom: 1px solid #eef0f3; padding: 10px; }.case-row:has(button:hover), .case-row.active { background: #ecf5ff; }.case-row button { display: grid; gap: 5px; border: 0; background: transparent; text-align: left; cursor: pointer; min-width: 0; }.case-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #475467; }.case-row small { color: #667085; }
.case-detail { min-width: 0; }.case-detail h3 { font-size: 15px; margin: 18px 0 8px; }.metadata-line { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; color: #667085; }.turns { background: #f8fafc; border: 1px solid #e4e7ed; padding: 8px 14px; max-height: 420px; overflow: auto; }.turn-row { display: grid; grid-template-columns: 28px 48px minmax(0, 1fr); align-items: start; gap: 4px; margin: 4px -6px; padding: 7px 6px; border-radius: 4px; }.turn-row.target { background: #eaf3ff; }.turn-spacer { width: 28px; }.claim-form { border: 1px solid #dcdfe6; padding: 12px; margin-bottom: 10px; }.claim-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }.claim-form :deep(.el-row) { margin-bottom: 10px; }.actions { display: flex; gap: 10px; margin-top: 18px; }
@media (max-width: 800px) { .accuracy-workbench { padding: 14px; }.page-header { display: grid; }.header-controls { justify-content: flex-start; }.workbench-grid { grid-template-columns: 1fr; }.case-list { border-right: 0; max-height: 260px; }.claim-form :deep(.el-col) { width: 100%; max-width: 100%; flex: 0 0 100%; margin-bottom: 8px; } }
</style>
