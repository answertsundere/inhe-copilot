<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getRealAccuracyCases, saveRealAccuracyLabel, type AccuracyClaim } from '../api/realAccuracy'

const loading = ref(false)
const saving = ref(false)
const cases = ref<any[]>([])
const selected = ref<any | null>(null)
const error = ref('')
const form = reactive<{ claims: AccuracyClaim[]; targetTurnUids: string[]; reviewStatus: 'draft' | 'reviewed' | 'approved'; version: number }>({
  claims: [], targetTurnUids: [], reviewStatus: 'draft', version: 0,
})

const statusText: Record<string, string> = {
  claim_label_pending: '待拆分断言', claim_accuracy_scorable: '可计入准确率',
  safety_scorable: '仅安全评估', context_gap: '上下文缺失', media_only: '仅图片/链接',
  privacy_review_required: '隐私待复核', invalid: '无效样本', label_gap: '待补标签',
}
const canApprove = computed(() => form.claims.length > 0 && form.targetTurnUids.length > 0)

function emptyClaim(): AccuracyClaim {
  return {
    claim_uid: `claim_${Date.now()}`, claim_kind: 'product_fact', query_fact_type: '', attribute_key: '',
    expected_status: 'unresolved', acceptable_values: [], normalized_value: null, unit: null,
    required_terms: [], supporting_evidence_uids: [], required_tool: null, required_action_points: [],
    must_handoff: true, forbidden_claims: [], partial_answer_allowed: false, review_status: 'draft',
  }
}
function split(value: string) { return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean) }
function join(value: string[] | undefined) { return (value || []).join('，') }

async function load() {
  loading.value = true; error.value = ''
  try {
    const { data } = await getRealAccuracyCases()
    cases.value = data.items || []
    if (cases.value.length) select(cases.value[0])
  } catch (e: any) {
    error.value = e?.response?.data?.error === 'gold_set_not_configured'
      ? '当前没有可用的脱敏 Gold Set，暂不能开始人工标注。'
      : '加载评测样本失败。'
  } finally { loading.value = false }
}
function select(item: any) {
  selected.value = item
  const saved = item.label
  form.claims = saved?.label?.claims ? JSON.parse(JSON.stringify(saved.label.claims)) : []
  form.targetTurnUids = saved?.label?.target_turn_uids ? [...saved.label.target_turn_uids] : []
  form.reviewStatus = saved?.review_status || 'draft'
  form.version = saved?.optimistic_lock_version || 0
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
    ElMessage.success(status === 'approved' ? '已批准，可计入准确率' : '已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <main class="page-container accuracy-workbench">
    <header class="page-header">
      <div><h2>准确率人工标注</h2><p>只处理已脱敏评测样本；这里的标签只用于评测，不会写入商品知识或客服回复。</p></div>
    </header>
    <el-alert v-if="error" type="warning" :closable="false" :title="error" />
    <section v-else class="workbench-grid" v-loading="loading">
      <aside class="case-list" aria-label="评测样本列表">
        <button v-for="item in cases" :key="item.case_uid" class="case-row" :class="{ active: selected?.case_uid === item.case_uid }" @click="select(item)">
          <strong>{{ statusText[item.classification] || '待处理' }}</strong><span>{{ item.customer_message }}</span>
        </button>
      </aside>
      <section v-if="selected" class="case-detail">
        <el-alert v-if="selected.privacy_review_required" type="error" :closable="false" title="该样本仍需隐私复核，不能批准标签。" />
        <h3>买家问题</h3><p>{{ selected.customer_message }}</p>
        <h3>选择本次要评分的买家问题</h3>
        <el-alert type="info" :closable="false" title="只勾选人工参考答案实际对应的买家消息。Agent 只会看到所选消息及其之前的对话。" />
        <div class="turns">
          <label v-for="turn in selected.conversation.turns" :key="turn.turn_uid" class="turn-row" :class="{ target: form.targetTurnUids.includes(turn.turn_uid) }">
            <el-checkbox v-if="turn.speaker_role === 'BUYER'" v-model="form.targetTurnUids" :value="turn.turn_uid" />
            <span v-else class="turn-spacer" />
            <b>{{ turn.speaker_role === 'BUYER' ? '买家' : turn.speaker_role === 'AGENT' ? '客服' : '系统' }}：</b>
            <span>{{ turn.text }}</span>
          </label>
        </div>
        <h3>人工参考答案</h3><p>{{ selected.reference_label.reference_text || '暂无人工参考答案' }}</p>
        <h3>评测断言</h3>
        <article v-for="(claim, index) in form.claims" :key="claim.claim_uid" class="claim-form">
          <el-row :gutter="12"><el-col :span="8"><el-input v-model="claim.query_fact_type" placeholder="问题类型" /></el-col><el-col :span="8"><el-input v-model="claim.attribute_key" placeholder="属性，例如宽度" /></el-col><el-col :span="8"><el-select v-model="claim.expected_status"><el-option label="有证据支持" value="supported" /><el-option label="无法确认" value="unresolved" /><el-option label="证据冲突" value="conflicting" /><el-option label="禁止断言" value="prohibited" /></el-select></el-col></el-row>
          <el-row :gutter="12"><el-col :span="12"><el-input :model-value="join(claim.required_terms)" @update:model-value="claim.required_terms = split($event)" placeholder="回复必须包含的词，用逗号分隔" /></el-col><el-col :span="12"><el-input :model-value="join(claim.supporting_evidence_uids)" @update:model-value="claim.supporting_evidence_uids = split($event)" placeholder="正式证据 UID（商品事实必填）" /></el-col></el-row>
          <el-checkbox v-model="claim.must_handoff">必须人工复核</el-checkbox><el-checkbox v-model="claim.partial_answer_allowed">允许部分回答</el-checkbox><el-button link type="danger" @click="form.claims.splice(index, 1)">删除</el-button>
        </article>
        <el-button @click="form.claims.push(emptyClaim())">新增断言</el-button>
        <div class="actions"><el-button :loading="saving" @click="save('draft')">保存草稿</el-button><el-button :disabled="!canApprove" :loading="saving" @click="save('reviewed')">提交复核</el-button><el-button type="primary" :disabled="!canApprove || selected.privacy_review_required" :loading="saving" @click="save('approved')">主管批准</el-button></div>
      </section>
    </section>
  </main>
</template>

<style scoped>
.accuracy-workbench { max-width: 1440px; margin: 0 auto; padding: 24px; }
.page-header h2 { margin: 0; font-size: 22px; }.page-header p { color: #667085; margin: 8px 0 20px; }
.workbench-grid { display: grid; grid-template-columns: minmax(260px, 320px) minmax(0, 1fr); gap: 20px; min-height: 600px; }
.case-list { border-right: 1px solid #e4e7ed; overflow: auto; }.case-row { display: grid; gap: 6px; width: 100%; text-align: left; border: 0; border-bottom: 1px solid #eef0f3; background: white; padding: 12px; cursor: pointer; }.case-row.active { background: #ecf5ff; }.case-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #475467; }
.case-detail { min-width: 0; }.case-detail h3 { font-size: 15px; margin: 18px 0 8px; }.turns { background: #f8fafc; border: 1px solid #e4e7ed; padding: 8px 14px; max-height: 420px; overflow: auto; }.turn-row { display: grid; grid-template-columns: 28px 48px minmax(0, 1fr); align-items: start; gap: 4px; margin: 4px -6px; padding: 7px 6px; border-radius: 4px; }.turn-row.target { background: #eaf3ff; }.turn-spacer { width: 28px; }.claim-form { border: 1px solid #dcdfe6; padding: 12px; margin-bottom: 10px; }.claim-form :deep(.el-row) { margin-bottom: 10px; }.actions { display: flex; gap: 10px; margin-top: 18px; }
@media (max-width: 800px) { .accuracy-workbench { padding: 14px; }.workbench-grid { grid-template-columns: 1fr; }.case-list { border-right: 0; max-height: 230px; }.claim-form :deep(.el-col) { width: 100%; max-width: 100%; flex: 0 0 100%; margin-bottom: 8px; } }
</style>
