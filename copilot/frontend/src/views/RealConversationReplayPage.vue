<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  approveKnowledgeGapTask,
  fetchEvalTrends,
  fetchKnowledgeGapPublishQueue,
  fetchKnowledgeGapTask,
  fetchKnowledgeGapTasks,
  fetchRealConversationQualityTasks,
  fetchRealConversationRun,
  fetchRealConversationRuns,
  fetchRepairTask,
  fetchRepairTasks,
  generateRealConversationQualityTasks,
  generateKnowledgeGapDraft,
  generateKnowledgeGapTasks,
  markKnowledgeGapDraftReady,
  generateRepairTasks,
  dryRunKnowledgeGapPublishQueue,
  previewKnowledgeGapPublishExport,
  previewKnowledgeGapPrePublishRetest,
  previewKnowledgeGapRetest,
  rejectKnowledgeGapTask,
  reviewKnowledgeGapDraft,
  runKnowledgeGapPrePublishRetest,
  retestKnowledgeGapTask,
  simulateKnowledgeGapPublish,
  submitRealConversationReview,
  triageKnowledgeGapTask,
  updateKnowledgeGapTask,
  updateKnowledgeGapStatus,
  updateRepairTask,
  updateKnowledgeGapPublishQueue,
  verifyKnowledgeGapTask,
  verifyRepairTask,
  type EvalTrends,
  type KnowledgeGapDraft,
  type KnowledgeGapPublishQueueItem,
  type KnowledgeGapSample,
  type KnowledgeGapSummary,
  type KnowledgeGapTask,
  type RealConversationFailure,
  type RealConversationQualityTaskGroup,
  type RealConversationQualityTasks,
  type RealConversationRepairTask,
  type RealConversationRun,
  type RealConversationRunSummary,
  type RealConversationTurnTrace,
  type ReviewDecision,
} from '../api/realConversationEval'

type TurnFilter =
  | 'all'
  | 'failed'
  | 'human_review'
  | 'rag_miss'
  | 'evidence_misuse'
  | 'semantic_mismatch'
  | 'unsafe_claim'
  | 'tool_policy_blocked'
  | 'wrong_topic_reply'
  | 'context_insufficient'
  | 'unnecessary_rag_call'
  | 'query_fact_type_missing'
  | 'not_scored'
  | 'bucket_auto_sendable'
  | 'bucket_safe_handoff'
  | 'bucket_context_gap'
  | 'bucket_knowledge_gap'
  | 'bucket_agent_error'
  | 'bucket_unscored_or_noise'

const loading = ref(false)
const forbidden = ref(false)
const runs = ref<RealConversationRun[]>([])
const selectedRun = ref<RealConversationRun | null>(null)
const runSummary = ref<RealConversationRunSummary | null>(null)
const turns = ref<RealConversationTurnTrace[]>([])
const failures = ref<RealConversationFailure[]>([])
const selectedTurn = ref<RealConversationTurnTrace | null>(null)
const reviewReason = ref('')
const activeFilter = ref<TurnFilter>('all')
const repairTasks = ref<RealConversationRepairTask[]>([])
const selectedTask = ref<RealConversationRepairTask | null>(null)
const selectedTaskTraces = ref<RealConversationTurnTrace[]>([])
const selectedTaskFailures = ref<RealConversationFailure[]>([])
const qualityTasks = ref<RealConversationQualityTasks | null>(null)
const qualityTaskBucketFilter = ref('')
const qualityTaskOwnerFilter = ref('')
const qualityTaskFixAreaFilter = ref('')
const qualityTaskPriorityFilter = ref('')
const taskStatusFilter = ref('')
const taskFixAreaFilter = ref('')
const taskOwnerFilter = ref('')
const taskAssignedTo = ref('')
const taskResolutionNote = ref('')
const trendDays = ref(7)
const trends = ref<EvalTrends | null>(null)
const knowledgeGapTasks = ref<KnowledgeGapTask[]>([])
const knowledgeGapSummary = ref<KnowledgeGapSummary | null>(null)
const selectedKnowledgeGap = ref<KnowledgeGapTask | null>(null)
const selectedKnowledgeGapSamples = ref<KnowledgeGapSample[]>([])
const selectedKnowledgeGapDrafts = ref<KnowledgeGapDraft[]>([])
const knowledgeGapPublishQueue = ref<KnowledgeGapPublishQueueItem[]>([])
const knowledgeGapPublishQueueSummary = ref<Record<string, unknown> | null>(null)
const knowledgeGapPublishQueueStatusFilter = ref('queued')
const knowledgeGapPublishQueueIncludeSuperseded = ref(false)
const knowledgeGapReviewNote = ref('')
const knowledgeGapVerifiedPayloadText = ref('')
const knowledgeGapQueueNote = ref('')
const knowledgeGapStatusFilter = ref('open')
const knowledgeGapTypeFilter = ref('')
const knowledgeGapEvidenceFilter = ref('')
const knowledgeGapTargetSystemFilter = ref('')
const knowledgeGapRiskFilter = ref('')
const knowledgeGapOwner = ref('')
const knowledgeGapRejectReason = ref('')
const knowledgeGapTriage = ref({
  review_decision: 'fill_product_field',
  assigned_team: '',
  assigned_to: '',
  priority: 'medium' as KnowledgeGapTask['priority'],
  due_date: '',
  review_note: '',
  next_action: '',
})

const filterOptions: Array<{ label: string; value: TurnFilter }> = [
  { label: '全部', value: 'all' },
  { label: '失败', value: 'failed' },
  { label: '需要人工复核', value: 'human_review' },
  { label: 'RAG 未命中', value: 'rag_miss' },
  { label: '证据错用', value: 'evidence_misuse' },
  { label: '语义不匹配', value: 'semantic_mismatch' },
  { label: '不安全承诺', value: 'unsafe_claim' },
  { label: '工具策略拦截', value: 'tool_policy_blocked' },
  { label: '答非所问', value: 'wrong_topic_reply' },
  { label: '上下文不足', value: 'context_insufficient' },
  { label: '不应查 RAG', value: 'unnecessary_rag_call' },
  { label: '意图为空', value: 'query_fact_type_missing' },
  { label: '跳过不评分', value: 'not_scored' },
]

filterOptions.push(
  { label: '自动可发', value: 'bucket_auto_sendable' },
  { label: '安全转人工', value: 'bucket_safe_handoff' },
  { label: '上下文缺口', value: 'bucket_context_gap' },
  { label: '知识/素材缺口', value: 'bucket_knowledge_gap' },
  { label: 'Agent 错误', value: 'bucket_agent_error' },
  { label: '未评分/噪声', value: 'bucket_unscored_or_noise' },
)

const reviewActions: Array<{ label: string; decision: ReviewDecision; type?: 'success' | 'danger' | 'warning' | 'primary' }> = [
  { label: '通过', decision: 'correct', type: 'success' },
  { label: '不通过', decision: 'incorrect', type: 'danger' },
  { label: '需要补知识', decision: 'needs_knowledge', type: 'primary' },
  { label: '需要改规则', decision: 'needs_rule', type: 'warning' },
  { label: '需要补素材', decision: 'needs_media' },
  { label: '需要人工策略', decision: 'needs_human_policy' },
]

const taskStatusOptions = [
  { label: '全部状态', value: '' },
  { label: 'open', value: 'open' },
  { label: 'in_progress', value: 'in_progress' },
  { label: 'resolved', value: 'resolved' },
  { label: 'ignored', value: 'ignored' },
]

const taskPriorityOptions = [
  { label: 'low', value: 'low' },
  { label: 'medium', value: 'medium' },
  { label: 'high', value: 'high' },
]

const trendDayOptions = [
  { label: '7 天', value: 7 },
  { label: '14 天', value: 14 },
  { label: '30 天', value: 30 },
]

const knowledgeGapStatusOptions = [
  { label: 'all status', value: '' },
  { label: 'open', value: 'open' },
  { label: 'triaged', value: 'triaged' },
  { label: 'assigned', value: 'assigned' },
  { label: 'draft_ready', value: 'draft_ready' },
  { label: 'waiting_data', value: 'waiting_data' },
  { label: 'pending_review', value: 'pending_review' },
  { label: 'approved', value: 'approved' },
  { label: 'rejected', value: 'rejected' },
  { label: 'resolved_pending_retest', value: 'resolved_pending_retest' },
  { label: 'verified', value: 'verified' },
  { label: 'closed', value: 'closed' },
]

const knowledgeGapReviewDecisionOptions = [
  { label: '补商品字段', value: 'fill_product_field' },
  { label: '补素材', value: 'upload_media_asset' },
  { label: '补售后规则', value: 'write_aftersales_policy' },
  { label: '补活动规则', value: 'write_promotion_policy' },
  { label: '修上下文抽取', value: 'fix_context_extraction' },
  { label: '修证据映射', value: 'improve_evidence_mapping' },
  { label: '忽略误报', value: 'ignore_false_positive' },
  { label: '需要更多样本', value: 'needs_more_samples' },
]

const knowledgeGapRiskOptions = [
  { label: 'all risk', value: '' },
  { label: 'high', value: 'high' },
  { label: 'medium', value: 'medium' },
  { label: 'low', value: 'low' },
]

const failuresByTurn = computed(() => {
  const map = new Map<string, RealConversationFailure[]>()
  for (const failure of failures.value) {
    if (!map.has(failure.turn_uid)) map.set(failure.turn_uid, [])
    map.get(failure.turn_uid)!.push(failure)
  }
  return map
})

const filteredTurns = computed(() => {
  if (activeFilter.value === 'all') return turns.value
  return turns.value.filter((turn) => {
    const turnFailures = failuresByTurn.value.get(turn.turn_uid) || []
    if (activeFilter.value === 'failed') return !turn.passed || turnFailures.length > 0
    if (activeFilter.value === 'human_review') return turn.requires_human_review
    if (activeFilter.value === 'not_scored') return turn.turn_understanding?.should_score === false
    if (activeFilter.value.startsWith('bucket_')) {
      return turn.quality_bucket === activeFilter.value.replace('bucket_', '')
    }
    return turnFailures.some((failure) => failure.failure_type === activeFilter.value)
  })
})

const groupedTurns = computed(() => {
  const groups = new Map<string, RealConversationTurnTrace[]>()
  for (const turn of filteredTurns.value) {
    const key = turn.case_uid || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(turn)
  }
  return Array.from(groups.entries()).map(([caseUid, items]) => ({ caseUid, items }))
})

const selectedFailures = computed(() => {
  if (!selectedTurn.value) return []
  return failuresByTurn.value.get(selectedTurn.value.turn_uid) || []
})

const taskFixAreaOptions = computed(() => {
  const values = Array.from(new Set(repairTasks.value.map((task) => task.suggested_fix_area).filter(Boolean))).sort()
  return [{ label: '全部修复区域', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const taskOwnerOptions = computed(() => {
  const values = Array.from(new Set(repairTasks.value.map((task) => task.suggested_owner).filter(Boolean))).sort()
  return [{ label: '全部负责人', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const qualityTaskGroups = computed<RealConversationQualityTaskGroup[]>(() => {
  const items = qualityTasks.value?.task_groups || []
  return items.filter((group) => {
    if (qualityTaskBucketFilter.value && group.quality_bucket !== qualityTaskBucketFilter.value) return false
    if (qualityTaskOwnerFilter.value && group.suggested_owner !== qualityTaskOwnerFilter.value) return false
    if (qualityTaskFixAreaFilter.value && group.suggested_fix_area !== qualityTaskFixAreaFilter.value) return false
    if (qualityTaskPriorityFilter.value && group.priority !== qualityTaskPriorityFilter.value) return false
    return true
  })
})

const qualityTaskBucketOptions = computed(() => {
  const values = Object.keys(qualityTasks.value?.summary || {}).sort()
  return [{ label: 'all buckets', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const qualityTaskOwnerOptions = computed(() => {
  const values = Array.from(new Set((qualityTasks.value?.task_groups || []).map((task) => task.suggested_owner).filter(Boolean))).sort()
  return [{ label: 'all owners', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const qualityTaskFixAreaOptions = computed(() => {
  const values = Array.from(new Set((qualityTasks.value?.task_groups || []).map((task) => task.suggested_fix_area).filter(Boolean))).sort()
  return [{ label: 'all fix areas', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const trendTotals = computed(() => {
  const daily = trends.value?.daily || []
  const totalTurns = daily.reduce((sum, item) => sum + (item.total_turns || 0), 0)
  const failedTurns = daily.reduce((sum, item) => sum + (item.failed_turns || 0), 0)
  return {
    totalTurns,
    failedTurns,
    passRate: totalTurns ? (totalTurns - failedTurns) / totalTurns : 0,
  }
})

const knowledgeGapTypeOptions = computed(() => {
  const values = Array.from(new Set(knowledgeGapTasks.value.map((task) => task.gap_category || task.gap_type).filter(Boolean))).sort()
  return [{ label: 'all gap categories', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const knowledgeGapEvidenceOptions = computed(() => {
  const values = Array.from(new Set(knowledgeGapTasks.value.map((task) => task.required_evidence_type || task.missing_evidence_type).filter(Boolean))).sort()
  return [{ label: 'all evidence types', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const knowledgeGapTargetSystemOptions = computed(() => {
  const values = Array.from(new Set(knowledgeGapTasks.value.map((task) => task.target_system).filter(Boolean))).sort()
  return [{ label: 'all target systems', value: '' }, ...values.map((value) => ({ label: value, value }))]
})

const latestKnowledgeGapDraft = computed(() => selectedKnowledgeGapDrafts.value[0] || null)
const latestKnowledgeGapDraftContent = computed(() => latestKnowledgeGapDraft.value?.draft_content || {})
const canMarkKnowledgeGapDraftReady = computed(
  () => latestKnowledgeGapDraftContent.value.publish_readiness === 'ready_for_review',
)

function formatJson(value: unknown) {
  return JSON.stringify(value || {}, null, 2)
}

function formatPercent(value?: number) {
  if (typeof value !== 'number') return '0%'
  return `${Math.round(value * 1000) / 10}%`
}

function runPassRate(run: RealConversationRun) {
  return run.total_turns ? formatPercent(run.passed_turns / run.total_turns) : '0%'
}

async function loadRuns() {
  loading.value = true
  forbidden.value = false
  try {
    await loadTrends()
    runs.value = await fetchRealConversationRuns()
    if (runs.value.length) {
      await loadRun(runs.value[0])
    }
  } catch (error: any) {
    if (error?.response?.status === 403) forbidden.value = true
    else ElMessage.error(error?.response?.data?.error || '加载真实回放批次失败')
  } finally {
    loading.value = false
  }
}

async function loadTrends() {
  trends.value = await fetchEvalTrends({
    days: trendDays.value,
    source: 'real_conversation',
  })
}

async function loadRun(run: RealConversationRun) {
  selectedRun.value = run
  selectedTurn.value = null
  activeFilter.value = 'all'
  loading.value = true
  try {
    const data = await fetchRealConversationRun(run.run_uid)
    turns.value = data.turns || []
    failures.value = data.failures || []
    runSummary.value = data.summary || null
    selectedTurn.value = turns.value[0] || null
    await loadQualityTasks()
    await loadRepairTasks()
    await loadKnowledgeGaps()
    await loadKnowledgeGapPublishQueue()
  } catch (error: any) {
    if (error?.response?.status === 403) forbidden.value = true
    else ElMessage.error(error?.response?.data?.error || '加载回放详情失败')
  } finally {
    loading.value = false
  }
}

async function loadQualityTasks() {
  if (!selectedRun.value) {
    qualityTasks.value = null
    return
  }
  qualityTasks.value = await fetchRealConversationQualityTasks(selectedRun.value.run_uid)
}

async function review(decision: ReviewDecision) {
  if (!selectedTurn.value) return
  await submitRealConversationReview({
    run_uid: selectedTurn.value.run_uid,
    case_uid: selectedTurn.value.case_uid,
    turn_uid: selectedTurn.value.turn_uid,
    decision,
    reason: reviewReason.value,
  })
  reviewReason.value = ''
  ElMessage.success('复核结果已保存')
}

async function loadRepairTasks() {
  const items = await fetchRepairTasks({
    run_uid: selectedRun.value?.run_uid,
    status: taskStatusFilter.value || undefined,
    suggested_fix_area: taskFixAreaFilter.value || undefined,
    suggested_owner: taskOwnerFilter.value || undefined,
  })
  repairTasks.value = items
  if (selectedTask.value && !items.some((task) => task.task_uid === selectedTask.value?.task_uid)) {
    selectedTask.value = null
    selectedTaskTraces.value = []
    selectedTaskFailures.value = []
  }
}

async function loadKnowledgeGaps() {
  const result = await fetchKnowledgeGapTasks({
    run_uid: selectedRun.value?.run_uid || undefined,
    status: knowledgeGapStatusFilter.value || undefined,
    gap_category: knowledgeGapTypeFilter.value || undefined,
    required_evidence_type: knowledgeGapEvidenceFilter.value || undefined,
    target_system: knowledgeGapTargetSystemFilter.value || undefined,
    risk_level: knowledgeGapRiskFilter.value || undefined,
    suggested_owner: knowledgeGapOwner.value || undefined,
  })
  knowledgeGapTasks.value = result.items || []
  knowledgeGapSummary.value = result.summary || null
  if (
    selectedKnowledgeGap.value &&
    !knowledgeGapTasks.value.some((task) => task.task_uid === selectedKnowledgeGap.value?.task_uid)
  ) {
    selectedKnowledgeGap.value = null
    selectedKnowledgeGapSamples.value = []
    selectedKnowledgeGapDrafts.value = []
  }
}

async function loadKnowledgeGapPublishQueue() {
  const result = await fetchKnowledgeGapPublishQueue({
    status: knowledgeGapPublishQueueStatusFilter.value || undefined,
    include_superseded: knowledgeGapPublishQueueIncludeSuperseded.value,
  })
  knowledgeGapPublishQueue.value = result.items || []
  knowledgeGapPublishQueueSummary.value = result.summary || null
}

async function generateKnowledgeGapsForCurrentRun() {
  await ElMessageBox.confirm(
    'Only creates review tasks and drafts. It will not write product facts, media assets, or Agent rules. Continue?',
    'Generate knowledge gaps',
    {
      confirmButtonText: 'Generate',
      cancelButtonText: 'Cancel',
      type: 'warning',
    },
  )
  const result = await generateKnowledgeGapTasks(selectedRun.value?.run_uid)
  await loadKnowledgeGaps()
  ElMessage.success(`Generated ${result.generated} gap tasks, updated ${result.updated}`)
}

async function openKnowledgeGapTask(task: KnowledgeGapTask) {
  const detail = await fetchKnowledgeGapTask(task.task_uid)
  selectedKnowledgeGap.value = detail.task
  selectedKnowledgeGapSamples.value = detail.samples || []
  selectedKnowledgeGapDrafts.value = detail.drafts || []
  knowledgeGapReviewNote.value = ''
  knowledgeGapVerifiedPayloadText.value = formatJson(selectedKnowledgeGapDrafts.value[0]?.draft_content?.publish_payload || {})
  knowledgeGapOwner.value = detail.task.suggested_owner || knowledgeGapOwner.value
  knowledgeGapTriage.value = {
    review_decision: detail.task.review_decision || reviewDecisionForGap(detail.task),
    assigned_team: detail.task.assigned_team || detail.task.suggested_owner || '',
    assigned_to: detail.task.assigned_to || '',
    priority: detail.task.priority || 'medium',
    due_date: detail.task.due_date || '',
    review_note: detail.task.review_note || '',
    next_action: detail.task.next_action || detail.recommended_next_action || detail.task.recommended_action || '',
  }
}

function reviewDecisionForGap(task: KnowledgeGapTask) {
  const gap = task.gap_category || task.gap_type
  if (gap === 'media_asset_gap') return 'upload_media_asset'
  if (gap === 'aftersales_policy_gap') return 'write_aftersales_policy'
  if (gap === 'promotion_policy_gap') return 'write_promotion_policy'
  if (gap === 'context_extraction_gap') return 'fix_context_extraction'
  if (gap === 'evidence_routing_gap') return 'improve_evidence_mapping'
  return 'fill_product_field'
}

function formatStringList(value: unknown) {
  return Array.isArray(value) ? value.join(', ') : ''
}

function formatUnknownList(value: unknown) {
  if (!Array.isArray(value)) return ''
  return value.map((item) => String(item)).join(', ')
}

async function generateDraftForKnowledgeGap() {
  if (!selectedKnowledgeGap.value) return
  const result = await generateKnowledgeGapDraft(selectedKnowledgeGap.value.task_uid, { force_regenerate: false })
  selectedKnowledgeGapDrafts.value = [result.draft, ...selectedKnowledgeGapDrafts.value]
  await loadKnowledgeGaps()
  if (selectedKnowledgeGap.value) await openKnowledgeGapTask(selectedKnowledgeGap.value)
  ElMessage.success('Draft created for review. It was not published to the formal knowledge base.')
}

async function regenerateDraftForKnowledgeGap() {
  if (!selectedKnowledgeGap.value) return
  await ElMessageBox.confirm(
    'Regenerate the staging draft from the current task data? This will not publish anything.',
    'Regenerate staging draft',
    {
      confirmButtonText: 'Regenerate',
      cancelButtonText: 'Cancel',
      type: 'warning',
    },
  )
  const result = await generateKnowledgeGapDraft(selectedKnowledgeGap.value.task_uid, { force_regenerate: true })
  selectedKnowledgeGapDrafts.value = [result.draft, ...selectedKnowledgeGapDrafts.value]
  await loadKnowledgeGaps()
  if (selectedKnowledgeGap.value) await openKnowledgeGapTask(selectedKnowledgeGap.value)
  ElMessage.success('Draft regenerated for review.')
}

async function markSelectedKnowledgeGapDraftReady() {
  if (!selectedKnowledgeGap.value) return
  const result = await markKnowledgeGapDraftReady(selectedKnowledgeGap.value.task_uid)
  selectedKnowledgeGap.value = result.task
  selectedKnowledgeGapDrafts.value = [result.draft, ...selectedKnowledgeGapDrafts.value.filter((draft) => draft.draft_uid !== result.draft.draft_uid)]
  await loadKnowledgeGaps()
  ElMessage.success('Draft marked ready for supervisor review.')
}

function parseKnowledgeGapVerifiedPayload() {
  if (!knowledgeGapVerifiedPayloadText.value.trim()) return {}
  try {
    return JSON.parse(knowledgeGapVerifiedPayloadText.value)
  } catch {
    throw new Error('verified_payload must be valid JSON')
  }
}

async function approveKnowledgeGapDraftForQueue() {
  if (!selectedKnowledgeGap.value || !latestKnowledgeGapDraft.value) return
  await ElMessageBox.confirm(
    'This only adds an audited item to the publish queue. It will not write the formal knowledge base.',
    'Enter publish queue',
    {
      confirmButtonText: 'Enter queue',
      cancelButtonText: 'Cancel',
      type: 'warning',
    },
  )
  const verifiedPayload = parseKnowledgeGapVerifiedPayload()
  const result = await reviewKnowledgeGapDraft(
    selectedKnowledgeGap.value.task_uid,
    latestKnowledgeGapDraft.value.draft_uid,
    {
      decision: 'approve_for_queue',
      review_note: knowledgeGapReviewNote.value,
      verified_payload: verifiedPayload,
      review_checklist: {
        reviewer_checked_payload: true,
        reviewer_checked_scope: true,
        reviewer_checked_source: true,
      },
    },
  )
  selectedKnowledgeGap.value = result.task
  selectedKnowledgeGapDrafts.value = [result.draft, ...selectedKnowledgeGapDrafts.value.filter((draft) => draft.draft_uid !== result.draft.draft_uid)]
  await loadKnowledgeGaps()
  await loadKnowledgeGapPublishQueue()
  ElMessage.success('Draft entered publish queue for audited handoff.')
}

async function requestKnowledgeGapDraftChanges(decision: 'reject' | 'request_changes') {
  if (!selectedKnowledgeGap.value || !latestKnowledgeGapDraft.value) return
  const result = await reviewKnowledgeGapDraft(
    selectedKnowledgeGap.value.task_uid,
    latestKnowledgeGapDraft.value.draft_uid,
    {
      decision,
      review_note: knowledgeGapReviewNote.value,
    },
  )
  selectedKnowledgeGap.value = result.task
  selectedKnowledgeGapDrafts.value = [result.draft, ...selectedKnowledgeGapDrafts.value.filter((draft) => draft.draft_uid !== result.draft.draft_uid)]
  await loadKnowledgeGaps()
  ElMessage.success(decision === 'reject' ? 'Draft rejected.' : 'Draft change request saved.')
}

async function previewPublishQueueItem(item: KnowledgeGapPublishQueueItem) {
  const result = await previewKnowledgeGapPublishExport(item.queue_uid)
  ElMessageBox.alert(formatJson(result.payload_preview), 'Export preview', {
    confirmButtonText: 'Close',
  })
}

function queueDryRunResult(item: KnowledgeGapPublishQueueItem) {
  return (item.publish_dry_run_result || {}) as Record<string, unknown>
}

function queueDryRunList(item: KnowledgeGapPublishQueueItem, key: string) {
  const value = queueDryRunResult(item)[key]
  return Array.isArray(value) ? value.map((entry) => String(entry)) : []
}

function queuePublishSimulationAudit(item: KnowledgeGapPublishQueueItem) {
  return (item.metadata?.last_publish_simulation_audit || {}) as Record<string, unknown>
}

function queuePublishSimulationPlan(item: KnowledgeGapPublishQueueItem) {
  return (item.metadata?.last_publish_simulation_plan || {}) as Record<string, unknown>
}

async function dryRunPublishQueueItem(item: KnowledgeGapPublishQueueItem) {
  await ElMessageBox.confirm(
    '本阶段只做发布前模拟校验，不写正式库。继续执行 dry-run？',
    '发布前 Dry-run',
    {
      confirmButtonText: '执行 Dry-run',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
  const result = await dryRunKnowledgeGapPublishQueue(item.queue_uid)
  knowledgeGapPublishQueue.value = knowledgeGapPublishQueue.value.map((row) =>
    row.queue_uid === item.queue_uid ? result.queue_item : row,
  )
  const ready = result.queue_item.ready_for_publish
  if (ready) {
    ElMessage.success('Dry-run passed. Ready for publish handoff.')
  } else {
    ElMessage.warning('Dry-run failed. Check block reasons.')
  }
}

function canRunPrePublishRetest(item: KnowledgeGapPublishQueueItem) {
  return (
    (item.status === 'queued' || item.status === 'exported') &&
    item.publish_dry_run_status === 'passed' &&
    item.ready_for_publish === true
  )
}

async function previewPrePublishRetest(item: KnowledgeGapPublishQueueItem) {
  const result = await previewKnowledgeGapPrePublishRetest(item.queue_uid)
  ElMessageBox.alert(formatJson(result), 'Pre-publish retest preview', {
    confirmButtonText: 'Close',
  })
}

async function runPrePublishRetest(item: KnowledgeGapPublishQueueItem) {
  await ElMessageBox.confirm(
    '复测只验证关联真实样本，不写正式库。approved_to_publish 仍不是正式发布。继续？',
    '发布前复测',
    {
      confirmButtonText: '执行复测',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
  const result = await runKnowledgeGapPrePublishRetest(item.queue_uid)
  knowledgeGapPublishQueue.value = knowledgeGapPublishQueue.value.map((row) =>
    row.queue_uid === item.queue_uid ? result.queue_item : row,
  )
  if (result.queue_item.approved_to_publish) {
    ElMessage.success('Pre-publish retest passed. Candidate is approved for publish handoff only.')
  } else {
    ElMessage.warning('Pre-publish retest failed. Check remaining failures and block reasons.')
  }
}

function canSimulatePublish(item: KnowledgeGapPublishQueueItem) {
  return (
    (item.status === 'queued' || item.status === 'exported') &&
    item.publish_dry_run_status === 'passed' &&
    item.ready_for_publish === true &&
    item.pre_publish_retest_status === 'passed' &&
    item.approved_to_publish === true &&
    item.approval_status === 'approved_to_publish'
  )
}

async function simulatePublishQueueItem(item: KnowledgeGapPublishQueueItem) {
  await ElMessageBox.confirm(
    '本操作只生成服务端发布模拟和审计记录，不写正式知识库、商品库或素材库。继续？',
    '发布模拟',
    {
      confirmButtonText: '执行发布模拟',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
  const result = await simulateKnowledgeGapPublish(item.queue_uid)
  if (result.queue_item) {
    knowledgeGapPublishQueue.value = knowledgeGapPublishQueue.value.map((row) =>
      row.queue_uid === item.queue_uid ? result.queue_item as KnowledgeGapPublishQueueItem : row,
    )
  }
  const message = result.ok ? 'Publish simulation passed. No formal tables were written.' : 'Publish simulation blocked. Check audit reasons.'
  if (result.ok) {
    ElMessage.success(message)
  } else {
    ElMessage.warning(message)
  }
  ElMessageBox.alert(formatJson({
    audit_uid: result.audit_uid,
    status: result.status,
    block_reasons: result.block_reasons,
    writes_formal_tables: result.writes_formal_tables,
    transaction_plan: result.transaction_plan,
  }), '发布模拟结果', {
    confirmButtonText: 'Close',
  })
}

async function updatePublishQueueItemStatus(item: KnowledgeGapPublishQueueItem, status: 'exported' | 'rejected' | 'cancelled') {
  const result = await updateKnowledgeGapPublishQueue(item.queue_uid, {
    status,
    note: knowledgeGapQueueNote.value,
  })
  knowledgeGapPublishQueue.value = knowledgeGapPublishQueue.value.map((row) =>
    row.queue_uid === item.queue_uid ? result.queue_item : row,
  )
  await loadKnowledgeGapPublishQueue()
  ElMessage.success(`Queue item marked ${status}.`)
}

async function triageKnowledgeGap() {
  if (!selectedKnowledgeGap.value) return
  const result = await triageKnowledgeGapTask(selectedKnowledgeGap.value.task_uid, {
    review_decision: knowledgeGapTriage.value.review_decision,
    assigned_team: knowledgeGapTriage.value.assigned_team,
    assigned_to: knowledgeGapTriage.value.assigned_to,
    priority: knowledgeGapTriage.value.priority,
    due_date: knowledgeGapTriage.value.due_date,
    review_note: knowledgeGapTriage.value.review_note,
    next_action: knowledgeGapTriage.value.next_action,
    source_run_uid: selectedRun.value?.run_uid,
  })
  selectedKnowledgeGap.value = result.task
  await loadKnowledgeGaps()
  await openKnowledgeGapTask(result.task)
  ElMessage.success('Knowledge gap triage saved')
}

async function setKnowledgeGapStatus(status: KnowledgeGapTask['status']) {
  if (!selectedKnowledgeGap.value) return
  const result = await updateKnowledgeGapStatus(selectedKnowledgeGap.value.task_uid, {
    status,
    priority: selectedKnowledgeGap.value.priority,
    assigned_team: knowledgeGapTriage.value.assigned_team,
    assigned_to: knowledgeGapTriage.value.assigned_to,
    due_date: knowledgeGapTriage.value.due_date,
    review_note: knowledgeGapTriage.value.review_note,
    next_action: knowledgeGapTriage.value.next_action,
  })
  selectedKnowledgeGap.value = result.task
  await loadKnowledgeGaps()
  await openKnowledgeGapTask(result.task)
  ElMessage.success(`Task status changed to ${status}`)
}

async function saveKnowledgeGapTask() {
  if (!selectedKnowledgeGap.value) return
  const result = await updateKnowledgeGapTask(selectedKnowledgeGap.value.task_uid, {
    status: selectedKnowledgeGap.value.status,
    priority: selectedKnowledgeGap.value.priority,
    suggested_owner: selectedKnowledgeGap.value.suggested_owner,
    summary: selectedKnowledgeGap.value.summary,
  })
  selectedKnowledgeGap.value = result.task
  await loadKnowledgeGaps()
  ElMessage.success('Knowledge gap task updated')
}

async function approveKnowledgeGap() {
  if (!selectedKnowledgeGap.value) return
  await ElMessageBox.confirm(
    'Approve this staged draft for ops handoff only? This will not publish to the formal knowledge base.',
    'Approve staged draft',
    {
      confirmButtonText: 'Approve',
      cancelButtonText: 'Cancel',
      type: 'warning',
    },
  )
  const result = await approveKnowledgeGapTask(selectedKnowledgeGap.value.task_uid)
  selectedKnowledgeGap.value = result.task
  selectedKnowledgeGapDrafts.value = result.drafts || []
  await loadKnowledgeGaps()
}

async function rejectKnowledgeGap() {
  if (!selectedKnowledgeGap.value) return
  const result = await rejectKnowledgeGapTask(selectedKnowledgeGap.value.task_uid, knowledgeGapRejectReason.value)
  selectedKnowledgeGap.value = result.task
  selectedKnowledgeGapDrafts.value = result.drafts || []
  knowledgeGapRejectReason.value = ''
  await loadKnowledgeGaps()
}

async function verifyKnowledgeGap() {
  if (!selectedKnowledgeGap.value) return
  await ElMessageBox.confirm(
    'This only records a manual staging check. It will not mark the task verified, run replay, or publish to the formal knowledge base. Continue?',
    'Manual staging check',
    {
      confirmButtonText: 'Record check',
      cancelButtonText: 'Cancel',
      type: 'warning',
    },
  )
  const result = await verifyKnowledgeGapTask(selectedKnowledgeGap.value.task_uid)
  selectedKnowledgeGap.value = result.task
  await loadKnowledgeGaps()
}

async function previewKnowledgeGapRetestScope() {
  if (!selectedKnowledgeGap.value) return
  const result = await previewKnowledgeGapRetest(selectedKnowledgeGap.value.task_uid)
  ElMessage.info(`Retest preview: ${result.sample_count} turn(s), ${result.case_uids.length} case(s).`)
}

async function runKnowledgeGapRetest() {
  if (!selectedKnowledgeGap.value) return
  await ElMessageBox.confirm(
    'Retest only verifies whether the current Agent can answer the linked real samples. It will not publish knowledge or media. Continue?',
    'Run knowledge gap retest',
    {
      confirmButtonText: 'Run retest',
      cancelButtonText: 'Cancel',
      type: 'warning',
    },
  )
  const result = await retestKnowledgeGapTask(selectedKnowledgeGap.value.task_uid, { apply: true })
  selectedKnowledgeGap.value = result.task
  await loadKnowledgeGaps()
  await openKnowledgeGapTask(result.task)
  const status = result.task.verification_status || 'unknown'
  if (status === 'verified_passed') {
    ElMessage.success('Retest passed. Task is now verified.')
  } else {
    ElMessage.warning(`Retest did not pass: ${status}`)
  }
}

async function generateQualityTasksForCurrentRun() {
  if (!selectedRun.value) return
  await ElMessageBox.confirm(
    'Generate dispatch tasks from quality buckets. This will not change product facts, media assets, or Agent rules. Continue?',
    'Generate quality tasks',
    {
      confirmButtonText: 'Generate',
      cancelButtonText: 'Cancel',
      type: 'warning',
    },
  )
  const result = await generateRealConversationQualityTasks(selectedRun.value.run_uid)
  await loadQualityTasks()
  await loadRepairTasks()
  await loadKnowledgeGaps()
  ElMessage.success(`Generated ${result.generated}, updated ${result.updated}, skipped ${result.skipped}`)
}

async function generateTasksForCurrentRun() {
  if (!selectedRun.value) return
  await ElMessageBox.confirm('只会生成质检修复任务，不会自动修改知识库或 Agent 规则。确认继续？', '生成修复任务', {
    confirmButtonText: '生成',
    cancelButtonText: '取消',
    type: 'warning',
  })
  const result = await generateRepairTasks(selectedRun.value.run_uid)
  await loadRepairTasks()
  ElMessage.success(`已生成 ${result.generated} 个任务，更新 ${result.updated} 个任务`)
}

async function openRepairTask(task: RealConversationRepairTask) {
  const detail = await fetchRepairTask(task.task_uid)
  selectedTask.value = detail.task
  selectedTaskTraces.value = detail.traces || []
  selectedTaskFailures.value = detail.failures || []
  taskAssignedTo.value = detail.task.assigned_to || ''
  taskResolutionNote.value = detail.task.resolution_note || ''
}

async function saveRepairTask(status?: RealConversationRepairTask['status'], priority?: RealConversationRepairTask['priority']) {
  if (!selectedTask.value) return
  const result = await updateRepairTask(selectedTask.value.task_uid, {
    status,
    priority,
    assigned_to: taskAssignedTo.value,
    resolution_note: taskResolutionNote.value,
  })
  selectedTask.value = result.task
  await loadRepairTasks()
  ElMessage.success('修复任务已更新')
}

async function previewRepairVerification() {
  if (!selectedTask.value) return
  const result = await verifyRepairTask(selectedTask.value.task_uid, { dry_run: true })
  ElMessage.info(`将验证 ${result.checked_turn_uids?.length || 0} 个关联轮次`)
}

async function runRepairVerification() {
  if (!selectedTask.value) return
  await ElMessageBox.confirm('会重新回放该任务关联样本，不会自动修改知识库或 Agent 规则。确认继续？', '回归验证', {
    confirmButtonText: '验证',
    cancelButtonText: '取消',
    type: 'warning',
  })
  const result = await verifyRepairTask(selectedTask.value.task_uid, { apply: true })
  if (result.task) {
    selectedTask.value = result.task
  }
  await loadRepairTasks()
  if (selectedTask.value) {
    await openRepairTask(selectedTask.value)
  }
  const status = result.task?.verification_status || 'unknown'
  ElMessage.success(`回归验证完成：${status}`)
}

onMounted(loadRuns)
</script>

<template>
  <div class="real-replay-page" v-loading="loading">
    <el-alert
      v-if="forbidden"
      title="当前角色无权访问运营监控"
      type="warning"
      show-icon
      :closable="false"
      class="permission-alert"
    />

    <template v-else>
      <aside class="run-list">
        <div class="panel-title">每日回放批次</div>
        <el-empty v-if="!runs.length" description="暂无回放批次" />
        <button
          v-for="run in runs"
          :key="run.run_uid"
          class="run-item"
          :class="{ active: selectedRun?.run_uid === run.run_uid }"
          @click="loadRun(run)"
        >
          <span class="run-id">{{ run.run_uid }}</span>
          <span class="run-meta">{{ run.status }} / 样本 {{ run.total_cases }} / 轮次 {{ run.total_turns }}</span>
          <span class="run-score">通过 {{ run.passed_turns }} / 失败 {{ run.failed_turns }} / 复核 {{ run.requires_review_turns }}</span>
          <span class="run-rate">通过率 {{ runPassRate(run) }}</span>
        </button>
      </aside>

      <main class="chat-panel">
        <div class="panel-title">真实长对话回放</div>

        <section class="trend-panel">
          <div class="trend-header">
            <div class="sub-title">趋势报表</div>
            <el-segmented v-model="trendDays" :options="trendDayOptions" size="small" @change="loadTrends" />
          </div>
          <div class="trend-cards">
            <div>
              <span>区间通过率</span>
              <strong>{{ formatPercent(trendTotals.passRate) }}</strong>
            </div>
            <div>
              <span>回放轮次</span>
              <strong>{{ trendTotals.totalTurns }}</strong>
            </div>
            <div>
              <span>失败轮次</span>
              <strong>{{ trendTotals.failedTurns }}</strong>
            </div>
            <div>
              <span>最近回放</span>
              <strong>{{ trends?.latest_daily_replay?.status || '-' }}</strong>
            </div>
          </div>
          <div class="trend-grid">
            <div class="trend-box">
              <div class="mini-title">每日通过率</div>
              <div v-for="item in trends?.daily || []" :key="item.date" class="daily-row">
                <span>{{ item.date }}</span>
                <el-progress :percentage="Math.round((item.pass_rate || 0) * 100)" :stroke-width="8" />
                <em>{{ item.total_turns }} 轮 / 失败 {{ item.failed_turns }} / 上下文 {{ item.context_gap_turns || 0 }}</em>
              </div>
            </div>
            <div class="trend-box">
              <div class="mini-title">Top 失败类型</div>
              <div v-for="item in trends?.top_failure_types || []" :key="item.name" class="rank-row">
                <span>{{ item.name }}</span>
                <strong>{{ item.count }}</strong>
              </div>
              <div class="mini-title">Top 修复区域</div>
              <div v-for="item in trends?.top_fix_areas || []" :key="item.name" class="rank-row">
                <span>{{ item.name }}</span>
                <strong>{{ item.count }}</strong>
              </div>
            </div>
            <div class="trend-box">
              <div class="mini-title">修复任务状态</div>
              <div v-for="(count, status) in trends?.repair_task_status_counts || {}" :key="status" class="rank-row">
                <span>{{ status }}</span>
                <strong>{{ count }}</strong>
              </div>
              <div class="mini-title">修复区域分布</div>
              <div v-for="(count, area) in trends?.suggested_fix_area_counts || {}" :key="area" class="rank-row">
                <span>{{ area }}</span>
                <strong>{{ count }}</strong>
              </div>
            </div>
          </div>
        </section>

        <section v-if="selectedRun" class="summary-strip">
          <div>
            <span>自动可发</span>
            <strong>{{ runSummary?.auto_sendable_turns || 0 }}</strong>
          </div>
          <div>
            <span>安全转人工</span>
            <strong>{{ runSummary?.safe_handoff_turns || 0 }}</strong>
          </div>
          <div>
            <span>上下文缺口</span>
            <strong>{{ runSummary?.context_gap_turns || 0 }}</strong>
          </div>
          <div>
            <span>侧栏商品覆盖</span>
            <strong>{{ formatPercent(runSummary?.sidecar_product_context_rate) }}</strong>
          </div>
          <div>
            <span>侧栏订单覆盖</span>
            <strong>{{ formatPercent(runSummary?.sidecar_order_context_rate) }}</strong>
          </div>
          <div>
            <span>缺侧栏上下文</span>
            <strong>{{ runSummary?.missing_sidecar_context_count || 0 }}</strong>
          </div>
          <div>
            <span>侧栏导致缺口</span>
            <strong>{{ runSummary?.context_gap_due_to_missing_sidecar_count || 0 }}</strong>
          </div>
          <div>
            <span>知识/素材缺口</span>
            <strong>{{ runSummary?.knowledge_gap_turns || 0 }}</strong>
          </div>
          <div>
            <span>Agent 错误</span>
            <strong>{{ runSummary?.agent_error_turns || 0 }}</strong>
          </div>
          <div>
            <span>未评分/噪声</span>
            <strong>{{ runSummary?.unscored_turns || 0 }}</strong>
          </div>
          <div>
            <span>通过率</span>
            <strong>{{ formatPercent(runSummary?.pass_rate) }}</strong>
          </div>
          <div>
            <span>平均耗时</span>
            <strong>{{ runSummary?.avg_latency_ms || 0 }} ms</strong>
          </div>
          <div>
            <span>人工复核</span>
            <strong>{{ runSummary?.requires_review_count || 0 }}</strong>
          </div>
          <div>
            <span>失败类型</span>
            <strong>{{ Object.keys(runSummary?.failure_counts_by_type || {}).length }}</strong>
          </div>
        </section>

        <el-segmented v-model="activeFilter" :options="filterOptions" class="filter-bar" />

        <el-empty v-if="!turns.length" description="选择左侧批次查看逐轮回放" />
        <el-empty v-else-if="!filteredTurns.length" description="当前筛选条件下没有样本" />
        <section v-for="group in groupedTurns" v-else :key="group.caseUid" class="conversation-group">
          <div class="case-title">{{ group.caseUid }}</div>
          <article
            v-for="turn in group.items"
            :key="turn.turn_uid"
            class="turn-card"
            :class="{ selected: selectedTurn?.turn_uid === turn.turn_uid, failed: !turn.passed }"
            @click="selectedTurn = turn"
          >
            <div class="turn-meta">
              <el-tag size="small" :type="turn.passed ? 'success' : 'danger'">
                {{ turn.passed ? '通过' : '失败' }}
              </el-tag>
              <el-tag v-if="turn.quality_bucket" size="small" type="primary">{{ turn.quality_bucket }}</el-tag>
              <el-tag v-if="turn.requires_human_review" size="small" type="warning">需人工复核</el-tag>
              <el-tag v-if="turn.query_fact_type" size="small">{{ turn.query_fact_type }}</el-tag>
              <el-tag v-if="turn.turn_understanding?.turn_actionability" size="small" type="info">
                {{ turn.turn_understanding.turn_actionability }}
              </el-tag>
              <el-tag v-if="turn.turn_understanding?.should_score === false" size="small">跳过不评分</el-tag>
              <el-tag v-if="turn.turn_understanding?.needs_rag === false" size="small">无需 RAG</el-tag>
              <span>{{ turn.latency_ms }} ms</span>
            </div>
            <div v-if="turn.quality_bucket_reason" class="quality-reason">
              {{ turn.quality_bucket_reason }}
            </div>
            <div class="bubble buyer">
              <span class="bubble-label">买家原话</span>
              <p>{{ turn.buyer_message }}</p>
            </div>
            <div class="bubble reference">
              <span class="bubble-label">原客服回复参考</span>
              <p>{{ turn.reference_human_reply || '-' }}</p>
            </div>
            <div class="bubble agent">
              <span class="bubble-label">Agent 回复</span>
              <p>{{ turn.agent_reply || '未生成回复' }}</p>
            </div>
            <div v-if="failuresByTurn.get(turn.turn_uid)?.length" class="failure-tags">
              <el-tag
                v-for="failure in failuresByTurn.get(turn.turn_uid)"
                :key="`${turn.turn_uid}-${failure.failure_type}`"
                size="small"
                type="danger"
              >
                {{ failure.failure_type }} / {{ failure.suggested_fix_area || 'manual_triage' }}
              </el-tag>
            </div>
            <div v-if="turn.is_knowledge_gap || turn.is_agent_error || turn.is_safe_handoff" class="quality-advice">
              <span v-if="turn.is_knowledge_gap">建议补资料/素材</span>
              <span v-else-if="turn.is_agent_error">建议修 Agent</span>
              <span v-else-if="turn.is_safe_handoff">安全转人工，不等同错答</span>
            </div>
          </article>
        </section>
      </main>

      <aside class="trace-panel">
        <div class="panel-title">RAG 命中与复核</div>
        <el-empty v-if="!selectedTurn" description="点击一轮对话查看 trace" />
        <template v-else>
          <div class="metric-grid">
            <div>
              <span>query_fact_type</span>
              <strong>{{ selectedTurn.query_fact_type || '-' }}</strong>
            </div>
            <div>
              <span>耗时</span>
              <strong>{{ selectedTurn.latency_ms }} ms</strong>
            </div>
            <div>
              <span>选中证据</span>
              <strong>{{ selectedTurn.selected_evidence.length }}</strong>
            </div>
            <div>
              <span>拒绝证据</span>
              <strong>{{ selectedTurn.rejected_evidence.length }}</strong>
            </div>
            <div>
              <span>turn_actionability</span>
              <strong>{{ selectedTurn.turn_understanding?.turn_actionability || '-' }}</strong>
            </div>
            <div>
              <span>reply_strategy</span>
              <strong>{{ selectedTurn.turn_understanding?.reply_strategy || '-' }}</strong>
            </div>
          </div>
          <section v-if="selectedTurn.turn_understanding" class="fix-panel">
            <div class="sub-title">Turn Understanding</div>
            <div class="fix-item">
              <span>needs_rag：{{ selectedTurn.turn_understanding.needs_rag }}</span>
              <span>should_score：{{ selectedTurn.turn_understanding.should_score }}</span>
              <span>skip_reason：{{ selectedTurn.turn_understanding.skip_reason || '-' }}</span>
              <span>forbidden_reply_topics：{{ selectedTurn.turn_understanding.forbidden_reply_topics?.join(', ') || '-' }}</span>
              <p>{{ selectedTurn.turn_understanding.reason || '-' }}</p>
            </div>
          </section>

          <section v-if="selectedFailures.length" class="fix-panel">
            <div class="sub-title">失败归因与修复建议</div>
            <div v-for="failure in selectedFailures" :key="failure.failure_type" class="fix-item">
              <strong>{{ failure.failure_type }}</strong>
              <span>严重度：{{ failure.severity }}</span>
              <span>修复区域：{{ failure.suggested_fix_area || 'manual_triage' }}</span>
              <span>建议负责人：{{ failure.suggested_owner || '-' }}</span>
              <p>{{ failure.explanation || failure.message }}</p>
            </div>
          </section>

          <el-collapse class="trace-collapse">
            <el-collapse-item title="selected_evidence" name="selected_evidence">
              <pre>{{ formatJson(selectedTurn.selected_evidence) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="rejected_evidence" name="rejected_evidence">
              <pre>{{ formatJson(selectedTurn.rejected_evidence) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="turn_understanding" name="turn_understanding">
              <pre>{{ formatJson(selectedTurn.turn_understanding) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="answer_trace" name="answer_trace">
              <pre>{{ formatJson(selectedTurn.answer_trace) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="final_audit" name="final_audit">
              <pre>{{ formatJson(selectedTurn.final_audit) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="semantic_compiler" name="semantic_compiler">
              <pre>{{ formatJson(selectedTurn.semantic_compiler) }}</pre>
            </el-collapse-item>
          </el-collapse>

          <el-input
            v-model="reviewReason"
            type="textarea"
            :rows="3"
            placeholder="人工复核备注，不会自动写知识库"
          />
          <div class="review-actions">
            <el-button
              v-for="action in reviewActions"
              :key="action.decision"
              :type="action.type"
              @click="review(action.decision)"
            >
              {{ action.label }}
            </el-button>
          </div>
        </template>
        <section class="repair-task-panel quality-task-panel">
          <div class="task-header">
            <div class="sub-title">Quality task groups</div>
            <el-button size="small" type="primary" :disabled="!selectedRun" @click="generateQualityTasksForCurrentRun">
              Generate dispatch tasks
            </el-button>
          </div>
          <div class="gap-cards">
            <div v-for="(count, bucket) in qualityTasks?.summary || {}" :key="bucket">
              <span>{{ bucket }}</span>
              <strong>{{ count }}</strong>
            </div>
          </div>
          <div class="task-filters">
            <el-select v-model="qualityTaskBucketFilter" size="small">
              <el-option
                v-for="option in qualityTaskBucketOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="qualityTaskOwnerFilter" size="small">
              <el-option
                v-for="option in qualityTaskOwnerOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="qualityTaskFixAreaFilter" size="small">
              <el-option
                v-for="option in qualityTaskFixAreaOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="qualityTaskPriorityFilter" size="small">
              <el-option label="all priorities" value="" />
              <el-option
                v-for="option in taskPriorityOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </div>
          <el-empty v-if="!qualityTaskGroups.length" description="No quality task groups" />
          <div v-else class="task-list">
            <article v-for="group in qualityTaskGroups" :key="group.task_group_uid" class="task-item">
              <strong>{{ group.quality_bucket }} / {{ group.primary_failure_type }}</strong>
              <span>{{ group.suggested_fix_area }} / {{ group.suggested_owner }} / {{ group.priority }}</span>
              <span>{{ group.query_fact_type || '-' }} / samples {{ group.sample_count }}</span>
              <span>{{ group.recommended_action }}</span>
              <div class="task-samples">
                <div v-for="sample in group.representative_samples" :key="sample.turn_uid" class="task-sample">
                  <strong>{{ sample.turn_uid }} / {{ sample.query_fact_type || '-' }}</strong>
                  <span>{{ sample.failure_labels.join(', ') || '-' }}</span>
                  <p>{{ sample.buyer_message_preview }}</p>
                  <p>{{ sample.agent_reply_preview }}</p>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section class="repair-task-panel">
          <div class="task-header">
            <div class="sub-title">修复任务队列</div>
            <el-button size="small" type="primary" :disabled="!selectedRun" @click="generateTasksForCurrentRun">
              从当前批次生成
            </el-button>
          </div>
          <div class="task-filters">
            <el-select v-model="taskStatusFilter" size="small" @change="loadRepairTasks">
              <el-option
                v-for="option in taskStatusOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="taskFixAreaFilter" size="small" @change="loadRepairTasks">
              <el-option
                v-for="option in taskFixAreaOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="taskOwnerFilter" size="small" @change="loadRepairTasks">
              <el-option
                v-for="option in taskOwnerOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </div>
          <el-empty v-if="!repairTasks.length" description="暂无修复任务" />
          <div v-else class="task-list">
            <button
              v-for="task in repairTasks"
              :key="task.task_uid"
              class="task-item"
              :class="{ active: selectedTask?.task_uid === task.task_uid }"
              @click="openRepairTask(task)"
            >
              <strong>{{ task.title || task.failure_type }}</strong>
              <span>{{ task.status }} / {{ task.priority }} / 样本 {{ task.sample_count }}</span>
              <span>验证 {{ task.verification_status }} / 通过率 {{ formatPercent(task.verification_summary?.pass_rate) }}</span>
              <span>{{ task.suggested_fix_area }} / {{ task.suggested_owner }}</span>
            </button>
          </div>
          <section v-if="selectedTask" class="task-detail">
            <div class="sub-title">任务详情</div>
            <p>{{ selectedTask.description }}</p>
            <div class="verification-panel">
              <div class="verification-line">
                <span>验证状态</span>
                <strong>{{ selectedTask.verification_status }}</strong>
              </div>
              <div class="verification-line">
                <span>上次验证</span>
                <strong>{{ selectedTask.last_verified_at || '-' }}</strong>
              </div>
              <div class="verification-line">
                <span>验证通过率</span>
                <strong>{{ formatPercent(selectedTask.verification_summary?.pass_rate) }}</strong>
              </div>
              <div v-if="selectedTask.verification_summary?.remaining_failure_types?.length" class="task-failure-tags">
                <el-tag
                  v-for="failureType in selectedTask.verification_summary.remaining_failure_types"
                  :key="failureType"
                  size="small"
                  type="danger"
                >
                  {{ failureType }}
                </el-tag>
              </div>
              <div class="task-controls">
                <el-button size="small" @click="previewRepairVerification">仅预览验证范围</el-button>
                <el-button size="small" type="warning" @click="runRepairVerification">回归验证</el-button>
              </div>
            </div>
            <div class="task-controls">
              <el-select v-model="selectedTask.status" size="small">
                <el-option
                  v-for="option in taskStatusOptions.filter((item) => item.value)"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-select v-model="selectedTask.priority" size="small">
                <el-option
                  v-for="option in taskPriorityOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </div>
            <el-input v-model="taskAssignedTo" size="small" placeholder="assigned_to" />
            <el-input
              v-model="taskResolutionNote"
              type="textarea"
              :rows="2"
              placeholder="处理备注，不会自动写知识库"
            />
            <el-button
              size="small"
              type="primary"
              @click="saveRepairTask(selectedTask.status, selectedTask.priority)"
            >
              保存任务状态
            </el-button>
            <div class="task-samples">
              <div v-if="selectedTaskFailures.length" class="task-failure-tags">
                <el-tag
                  v-for="failure in selectedTaskFailures"
                  :key="`${failure.turn_uid}-${failure.failure_type}`"
                  size="small"
                  type="danger"
                >
                  {{ failure.failure_type }}
                </el-tag>
              </div>
              <div v-for="trace in selectedTaskTraces" :key="trace.turn_uid" class="task-sample">
                <strong>{{ trace.turn_uid }}</strong>
                <span>{{ trace.query_fact_type || '-' }} / {{ trace.latency_ms }} ms</span>
                <p>{{ trace.buyer_message }}</p>
              </div>
            </div>
          </section>
        </section>
        <section class="knowledge-gap-panel">
          <div class="task-header">
            <div>
              <div class="sub-title">知识缺口治理</div>
              <p class="panel-hint">把真实回放失败沉淀为待补资料、素材、规则或人工策略任务。</p>
            </div>
            <el-button size="small" type="primary" @click="generateKnowledgeGapsForCurrentRun">
              生成缺口任务
            </el-button>
          </div>

          <div v-if="knowledgeGapSummary" class="gap-cards">
            <div>
              <span>{{ knowledgeGapSummary.filtered_by_run_uid ? 'current run tasks' : 'all tasks' }}</span>
              <strong>{{ knowledgeGapSummary.total ?? knowledgeGapTasks.length }}</strong>
            </div>
            <div>
              <span>open</span>
              <strong>{{ knowledgeGapSummary.open_count }}</strong>
            </div>
            <div>
              <span>high risk</span>
              <strong>{{ knowledgeGapSummary.high_risk_count }}</strong>
            </div>
            <div>
              <span>media</span>
              <strong>{{ knowledgeGapSummary.media_gap_count }}</strong>
            </div>
            <div>
              <span>drafts</span>
              <strong>{{ knowledgeGapSummary.draft_count }}</strong>
            </div>
          </div>

          <div class="task-filters">
            <el-select v-model="knowledgeGapStatusFilter" size="small" @change="loadKnowledgeGaps">
              <el-option
                v-for="option in knowledgeGapStatusOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="knowledgeGapTypeFilter" size="small" @change="loadKnowledgeGaps">
              <el-option
                v-for="option in knowledgeGapTypeOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="knowledgeGapEvidenceFilter" size="small" @change="loadKnowledgeGaps">
              <el-option
                v-for="option in knowledgeGapEvidenceOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="knowledgeGapTargetSystemFilter" size="small" @change="loadKnowledgeGaps">
              <el-option
                v-for="option in knowledgeGapTargetSystemOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select v-model="knowledgeGapRiskFilter" size="small" @change="loadKnowledgeGaps">
              <el-option
                v-for="option in knowledgeGapRiskOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </div>

          <el-empty v-if="!knowledgeGapTasks.length" description="鏆傛棤鐭ヨ瘑缂哄彛浠诲姟" />
          <div v-else class="gap-list">
            <button
              v-for="task in knowledgeGapTasks"
              :key="task.task_uid"
              class="gap-item"
              :class="{ active: selectedKnowledgeGap?.task_uid === task.task_uid }"
              @click="openKnowledgeGapTask(task)"
            >
              <strong>{{ task.gap_category || task.gap_type }} / {{ task.query_fact_type || '-' }}</strong>
              <span>{{ task.status }} / {{ task.priority }} / {{ task.risk_level }} / samples {{ task.sample_count }}</span>
              <span>需要：{{ task.required_evidence_type || task.missing_evidence_type || '-' }}</span>
              <span>补到：{{ task.target_system || '-' }} / {{ task.recommended_action || '-' }}</span>
              <span>{{ task.product_title_preview || task.product_title || task.item_id_masked || task.sku_code || 'unknown product' }}</span>
              <span>{{ task.suggested_fix_area }} / {{ task.suggested_owner }}</span>
              <span v-if="task.review_decision">review: {{ task.review_decision }}</span>
              <span v-if="task.assigned_to || task.assigned_team">
                assigned: {{ task.assigned_to || task.assigned_team }}
              </span>
              <span v-if="task.verification_status">retest: {{ task.verification_status }}</span>
            </button>
          </div>

          <section v-if="selectedKnowledgeGap" class="gap-detail">
            <div class="sub-title">缂哄彛璇︽儏</div>
            <p>{{ selectedKnowledgeGap.summary }}</p>
            <div class="gap-meta">
              <span>缺口类型：{{ selectedKnowledgeGap.gap_category || selectedKnowledgeGap.gap_type }}</span>
              <span>需要补：{{ selectedKnowledgeGap.required_evidence_type || selectedKnowledgeGap.missing_evidence_type || '-' }}</span>
              <span>补到：{{ selectedKnowledgeGap.target_system || '-' }}</span>
              <span>动作：{{ selectedKnowledgeGap.recommended_action || '-' }}</span>
              <span>缺失字段：{{ (selectedKnowledgeGap.missing_fields || []).join(', ') || '-' }}</span>
              <span>review_decision：{{ selectedKnowledgeGap.review_decision || '-' }}</span>
              <span>assigned：{{ selectedKnowledgeGap.assigned_to || selectedKnowledgeGap.assigned_team || '-' }}</span>
              <span>due：{{ selectedKnowledgeGap.due_date || '-' }}</span>
              <span>next：{{ selectedKnowledgeGap.next_action || '-' }}</span>
              <span>verification_status：{{ selectedKnowledgeGap.verification_status || 'not_verified' }}</span>
              <span>verification_run：{{ selectedKnowledgeGap.verification_run_uid || '-' }}</span>
              <span>last_verified_at：{{ selectedKnowledgeGap.last_verified_at || '-' }}</span>
              <span>
                上下文：
                product={{ Boolean(selectedKnowledgeGap.current_context_summary?.has_product_context) ? 'yes' : 'no' }},
                order={{ Boolean(selectedKnowledgeGap.current_context_summary?.has_order_context) ? 'yes' : 'no' }},
                media={{ Boolean(selectedKnowledgeGap.current_context_summary?.has_media_context) ? 'yes' : 'no' }}
              </span>
            </div>
            <div class="gap-triage-panel">
              <div class="mini-title">人工流转</div>
              <p class="safe-note">草稿只进入 staging 待审；这里不会写入正式知识库，也不会发布素材。</p>
              <div class="triage-grid">
                <el-select v-model="knowledgeGapTriage.review_decision" size="small">
                  <el-option
                    v-for="option in knowledgeGapReviewDecisionOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
                <el-input v-model="knowledgeGapTriage.assigned_team" size="small" placeholder="assigned_team" />
                <el-input v-model="knowledgeGapTriage.assigned_to" size="small" placeholder="assigned_to" />
                <el-select v-model="knowledgeGapTriage.priority" size="small">
                  <el-option
                    v-for="option in taskPriorityOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
                <el-input v-model="knowledgeGapTriage.due_date" size="small" placeholder="due date" />
                <el-input v-model="knowledgeGapTriage.next_action" size="small" placeholder="next action" />
              </div>
              <el-input
                v-model="knowledgeGapTriage.review_note"
                type="textarea"
                :rows="2"
                placeholder="review note"
              />
              <div class="gap-actions">
                <el-button size="small" type="primary" @click="triageKnowledgeGap">保存分派</el-button>
                <el-button size="small" @click="setKnowledgeGapStatus('waiting_data')">标记待补资料</el-button>
                <el-button size="small" @click="setKnowledgeGapStatus('resolved_pending_retest')">标记待复测</el-button>
                <el-button size="small" type="warning" @click="setKnowledgeGapStatus('rejected')">忽略/驳回</el-button>
              </div>
            </div>
            <div class="gap-retest-panel">
              <div class="mini-title">复测验证</div>
              <p class="safe-note">复测只验证当前 Agent 是否能回答关联样本；不会发布知识库，也不会发布素材。</p>
              <div class="gap-actions">
                <el-button size="small" @click="previewKnowledgeGapRetestScope">复测预览</el-button>
                <el-button
                  v-if="['resolved_pending_retest', 'waiting_data'].includes(selectedKnowledgeGap.status) && selectedKnowledgeGap.sample_count > 0"
                  size="small"
                  type="primary"
                  @click="runKnowledgeGapRetest"
                >
                  开始复测
                </el-button>
              </div>
              <div v-if="selectedKnowledgeGap.verification_summary" class="verification-lines">
                <span>pass_rate: {{ selectedKnowledgeGap.verification_summary.pass_rate ?? '-' }}</span>
                <span>failed_turns: {{ selectedKnowledgeGap.verification_summary.failed_turns ?? '-' }}</span>
                <span>agent_error: {{ selectedKnowledgeGap.verification_summary.agent_error_count ?? '-' }}</span>
                <span>knowledge_gap: {{ selectedKnowledgeGap.verification_summary.knowledge_gap_count ?? '-' }}</span>
                <span>safe_handoff: {{ selectedKnowledgeGap.verification_summary.safe_handoff_count ?? '-' }}</span>
                <span>
                  remaining:
                  {{ formatStringList(selectedKnowledgeGap.verification_summary.remaining_failure_types) || '-' }}
                </span>
              </div>
            </div>
            <div class="task-controls">
              <el-select v-model="selectedKnowledgeGap.status" size="small">
                <el-option
                  v-for="option in knowledgeGapStatusOptions.filter((item) => item.value)"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-select v-model="selectedKnowledgeGap.priority" size="small">
                <el-option
                  v-for="option in taskPriorityOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </div>
            <el-input v-model="selectedKnowledgeGap.suggested_owner" size="small" placeholder="suggested_owner" />
            <el-input
              v-model="selectedKnowledgeGap.summary"
              type="textarea"
              :rows="2"
              placeholder="任务摘要，不会自动写入正式知识库"
            />
            <div class="gap-actions">
              <el-button size="small" type="primary" @click="saveKnowledgeGapTask">保存</el-button>
              <el-button size="small" @click="generateDraftForKnowledgeGap">生成待审草稿</el-button>
              <el-button size="small" @click="regenerateDraftForKnowledgeGap">重新生成草稿</el-button>
              <el-button
                v-if="canMarkKnowledgeGapDraftReady"
                size="small"
                type="success"
                @click="markSelectedKnowledgeGapDraftReady"
              >
                标记待审核
              </el-button>
              <el-button size="small" type="success" @click="approveKnowledgeGap">审核通过</el-button>
              <el-button size="small" type="warning" @click="verifyKnowledgeGap">人工确认已验证</el-button>
            </div>
            <div v-if="latestKnowledgeGapDraft" class="gap-review-box">
              <div class="mini-title">Draft Review</div>
              <el-input
                v-model="knowledgeGapReviewNote"
                size="small"
                placeholder="review note"
              />
              <el-input
                v-model="knowledgeGapVerifiedPayloadText"
                type="textarea"
                :rows="7"
                placeholder="verified_payload JSON"
              />
              <div class="gap-actions">
                <el-button size="small" type="primary" @click="approveKnowledgeGapDraftForQueue">
                  进入发布队列
                </el-button>
                <el-button size="small" @click="requestKnowledgeGapDraftChanges('request_changes')">
                  要求修改
                </el-button>
                <el-button size="small" type="warning" @click="requestKnowledgeGapDraftChanges('reject')">
                  驳回草稿
                </el-button>
              </div>
            </div>
            <el-input
              v-model="knowledgeGapRejectReason"
              size="small"
              placeholder="椹冲洖鍘熷洜"
              class="gap-reject-input"
            />
            <el-button size="small" type="danger" @click="rejectKnowledgeGap">椹冲洖鑽夌</el-button>

            <div class="task-samples">
              <div v-for="sample in selectedKnowledgeGapSamples" :key="sample.turn_uid" class="gap-sample">
                <strong>{{ sample.failure_type }} / {{ sample.query_fact_type || '-' }}</strong>
                <span>{{ sample.turn_uid }}</span>
                <p>{{ sample.buyer_message }}</p>
              </div>
            </div>

            <div v-if="selectedKnowledgeGapDrafts.length" class="gap-drafts">
              <div v-for="draft in selectedKnowledgeGapDrafts" :key="draft.draft_uid" class="gap-draft">
                <strong>
                  {{ draft.draft_type }} / {{ draft.review_status }} / staging={{ draft.publish_target }}
                </strong>
                <div class="draft-fields">
                  <span>publish_readiness：{{ draft.draft_content.publish_readiness || '-' }}</span>
                  <span>
                    business target：{{ draft.draft_content.business_publish_target || draft.draft_content.target_system || '-' }}
                  </span>
                  <span>blocked reason：{{ draft.draft_content.publish_blocked_reason || '-' }}</span>
                  <span>required fields：{{ formatUnknownList(draft.draft_content.required_review_fields) || '-' }}</span>
                  <span>checklist：{{ formatUnknownList(draft.draft_content.reviewer_checklist) || '-' }}</span>
                </div>
                <details>
                  <summary>view publish candidate</summary>
                  <pre>{{ formatJson(draft.draft_content.publish_payload) }}</pre>
                </details>
                <pre>{{ formatJson(draft.draft_content) }}</pre>
              </div>
            </div>
            <div v-if="selectedKnowledgeGap.status_history?.length" class="gap-history">
              <div class="mini-title">状态历史</div>
              <div v-for="(item, index) in selectedKnowledgeGap.status_history" :key="index" class="history-row">
                <span>{{ item.status || '-' }}</span>
                <span>{{ item.changed_by || '-' }}</span>
                <span>{{ item.changed_at || '-' }}</span>
              </div>
            </div>
            <div class="gap-publish-queue">
              <div class="mini-title">Publish Queue</div>
              <div class="queue-toolbar">
                <el-select v-model="knowledgeGapPublishQueueStatusFilter" size="small" @change="loadKnowledgeGapPublishQueue">
                  <el-option label="queued" value="queued" />
                  <el-option label="exported" value="exported" />
                  <el-option label="rejected" value="rejected" />
                  <el-option label="cancelled" value="cancelled" />
                  <el-option label="superseded" value="superseded" />
                  <el-option label="all" value="" />
                </el-select>
                <el-input v-model="knowledgeGapQueueNote" size="small" placeholder="queue note" />
              </div>
              <el-checkbox v-model="knowledgeGapPublishQueueIncludeSuperseded" @change="loadKnowledgeGapPublishQueue">
                显示已作废候选
              </el-checkbox>
              <div class="queue-summary">
                total: {{ knowledgeGapPublishQueueSummary?.total ?? knowledgeGapPublishQueue.length }},
                active: {{ knowledgeGapPublishQueueSummary?.active_count ?? '-' }},
                superseded: {{ knowledgeGapPublishQueueSummary?.superseded_count ?? '-' }}
              </div>
              <el-empty v-if="!knowledgeGapPublishQueue.length" description="暂无发布队列候选" />
              <div v-for="item in knowledgeGapPublishQueue" :key="item.queue_uid" class="queue-item">
                <strong>{{ item.publish_target }} / {{ item.status }} / {{ item.export_status }}</strong>
                <span>{{ item.queue_uid }}</span>
                <span>fingerprint: {{ item.payload_fingerprint || '-' }}</span>
                <span>risk: {{ item.risk_level }} / reviewer: {{ item.reviewer || '-' }}</span>
                <span>
                  dry-run: {{ item.publish_dry_run_status || 'not_run' }} /
                  ready_for_publish: {{ item.ready_for_publish ? 'yes' : 'no' }}
                </span>
                <span>
                  pre-publish retest: {{ item.pre_publish_retest_status || 'not_run' }} /
                  approval: {{ item.approval_status || 'not_ready' }} /
                  approved_to_publish: {{ item.approved_to_publish ? 'yes' : 'no' }}
                </span>
                <span v-if="item.locked_payload_fingerprint">
                  locked fingerprint: {{ item.locked_payload_fingerprint }}
                </span>
                <span v-if="item.pre_publish_block_reasons?.length">
                  retest block reasons: {{ item.pre_publish_block_reasons.join('; ') }}
                </span>
                <span v-if="item.last_dry_run_at">
                  last dry-run: {{ item.last_dry_run_at }} / by {{ item.dry_run_by || '-' }}
                </span>
                <span v-if="item.publish_block_reasons?.length">
                  block reasons: {{ item.publish_block_reasons.join('; ') }}
                </span>
                <span v-if="item.superseded_reason">
                  superseded: {{ item.superseded_reason }} / by {{ item.superseded_by || '-' }} / at {{ item.superseded_at || '-' }}
                </span>
                <details v-if="Object.keys(queueDryRunResult(item)).length">
                  <summary>dry-run diff / checks</summary>
                  <div class="draft-fields">
                    <span>adapter: {{ queueDryRunResult(item).adapter || '-' }}</span>
                    <span>schema_valid: {{ queueDryRunResult(item).schema_valid }}</span>
                    <span>writes_formal_tables: {{ queueDryRunResult(item).writes_formal_tables }}</span>
                    <span>manual checks: {{ queueDryRunList(item, 'required_manual_checks').join('; ') || '-' }}</span>
                    <span>warnings: {{ queueDryRunList(item, 'warnings').join('; ') || '-' }}</span>
                  </div>
                  <pre>{{ formatJson(queueDryRunResult(item).diff_preview) }}</pre>
                </details>
                <details v-if="Object.keys(item.pre_publish_retest_summary || {}).length">
                  <summary>pre-publish retest summary</summary>
                  <pre>{{ formatJson(item.pre_publish_retest_summary) }}</pre>
                </details>
                <details v-if="Object.keys(queuePublishSimulationAudit(item)).length">
                  <summary>publish simulation audit</summary>
                  <div class="draft-fields">
                    <span>audit: {{ queuePublishSimulationAudit(item).audit_uid || '-' }}</span>
                    <span>status: {{ queuePublishSimulationAudit(item).status || '-' }}</span>
                    <span>writes_formal_tables: {{ queuePublishSimulationAudit(item).writes_formal_tables }}</span>
                    <span>created_at: {{ queuePublishSimulationAudit(item).created_at || '-' }}</span>
                    <span v-if="queuePublishSimulationAudit(item).reason">reason: {{ queuePublishSimulationAudit(item).reason }}</span>
                  </div>
                </details>
                <details v-if="Object.keys(queuePublishSimulationPlan(item)).length">
                  <summary>publish transaction simulation plan</summary>
                  <p class="safe-note">当前为发布事务模拟计划，正式写库未启用。</p>
                  <div class="draft-fields">
                    <span>plan_version: {{ queuePublishSimulationPlan(item).plan_version || '-' }}</span>
                    <span>publish_enabled: {{ queuePublishSimulationPlan(item).publish_enabled }}</span>
                    <span>writes_formal_tables: {{ queuePublishSimulationPlan(item).writes_formal_tables }}</span>
                    <span>rollback_supported: {{ queuePublishSimulationPlan(item).rollback_supported }}</span>
                  </div>
                  <pre>{{ formatJson(queuePublishSimulationPlan(item)) }}</pre>
                </details>
                <div class="gap-actions">
                  <el-button
                    v-if="item.status === 'queued' || item.status === 'exported'"
                    size="small"
                    type="primary"
                    @click="dryRunPublishQueueItem(item)"
                  >
                    发布前 Dry-run
                  </el-button>
                  <el-button
                    size="small"
                    :disabled="!canRunPrePublishRetest(item)"
                    @click="previewPrePublishRetest(item)"
                  >
                    复测预览
                  </el-button>
                  <el-button
                    size="small"
                    type="warning"
                    :disabled="!canRunPrePublishRetest(item)"
                    @click="runPrePublishRetest(item)"
                  >
                    发布前复测
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    :disabled="!canSimulatePublish(item)"
                    @click="simulatePublishQueueItem(item)"
                  >
                    发布模拟
                  </el-button>
                  <el-button size="small" @click="previewPublishQueueItem(item)">导出预览</el-button>
                  <el-button
                    v-if="item.status !== 'superseded'"
                    size="small"
                    type="success"
                    @click="updatePublishQueueItemStatus(item, 'exported')"
                  >
                    标记已导出
                  </el-button>
                  <el-button size="small" @click="updatePublishQueueItemStatus(item, 'cancelled')">取消</el-button>
                  <el-button size="small" type="warning" @click="updatePublishQueueItemStatus(item, 'rejected')">驳回</el-button>
                </div>
              </div>
            </div>
          </section>
        </section>
      </aside>
    </template>
  </div>
</template>

<style scoped>
.real-replay-page {
  display: grid;
  grid-template-columns: 280px minmax(460px, 1fr) 430px;
  gap: 16px;
  min-height: calc(100vh - 104px);
}

.permission-alert {
  grid-column: 1 / -1;
}

.run-list,
.chat-panel,
.trace-panel {
  min-height: 0;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 14px;
  overflow: auto;
}

.panel-title,
.sub-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--kb-text-primary);
  margin-bottom: 12px;
}

.sub-title {
  font-size: 13px;
  margin-bottom: 8px;
}

.run-item {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid var(--kb-border);
  background: #fff;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 10px;
  cursor: pointer;
}

.run-item.active {
  border-color: #3b82f6;
  background: #eff6ff;
}

.run-id,
.run-meta,
.run-score,
.run-rate {
  display: block;
}

.run-id {
  font-weight: 700;
  color: var(--kb-text-primary);
  font-size: 13px;
}

.run-meta,
.run-score,
.run-rate {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.trend-panel {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 10px;
  background: #fff;
  margin-bottom: 12px;
}

.trend-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.trend-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}

.trend-cards div,
.trend-box {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #f8fafc;
  padding: 8px;
}

.trend-cards span,
.daily-row span,
.daily-row em,
.rank-row span {
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.trend-cards strong {
  display: block;
  margin-top: 4px;
  color: var(--kb-text-primary);
}

.trend-grid {
  display: grid;
  grid-template-columns: minmax(240px, 1.2fr) 1fr 1fr;
  gap: 8px;
}

.mini-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--kb-text-primary);
  margin-bottom: 6px;
}

.daily-row {
  display: grid;
  grid-template-columns: 82px minmax(80px, 1fr) 86px;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.daily-row em {
  font-style: normal;
  text-align: right;
}

.rank-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
}

.summary-strip div,
.metric-grid div,
.fix-item {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 8px;
  background: #fff;
}

.summary-strip span,
.metric-grid span,
.fix-item span {
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.summary-strip strong,
.metric-grid strong {
  display: block;
  color: var(--kb-text-primary);
  margin-top: 4px;
}

.filter-bar {
  margin-bottom: 12px;
  max-width: 100%;
  overflow-x: auto;
}

.conversation-group {
  margin-bottom: 16px;
}

.case-title {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin: 12px 0 8px;
}

.turn-card {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fff;
  cursor: pointer;
}

.turn-card.selected {
  border-color: #3b82f6;
}

.turn-card.failed {
  border-color: #fca5a5;
}

.turn-meta,
.failure-tags,
.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.turn-meta {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-bottom: 10px;
}

.bubble {
  margin-bottom: 10px;
  border-radius: 8px;
  padding: 8px;
}

.bubble p,
.fix-item p {
  margin: 4px 0 0;
  line-height: 1.6;
  white-space: pre-wrap;
}

.bubble-label {
  font-size: 12px;
  color: var(--kb-text-secondary);
}

.buyer {
  background: #f0fdf4;
}

.reference {
  background: #fff7ed;
}

.agent {
  background: #f8fafc;
}

.failure-tags {
  margin-top: 8px;
}

.quality-reason,
.quality-advice {
  margin: 6px 0;
  color: var(--kb-text-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.quality-advice {
  color: #b45309;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.fix-panel,
.trace-collapse {
  margin-bottom: 12px;
}

.repair-task-panel,
.knowledge-gap-panel {
  border-top: 1px solid var(--kb-border);
  margin-top: 14px;
  padding-top: 14px;
}

.panel-hint {
  margin: 0;
  color: var(--kb-text-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.task-header,
.task-filters,
.task-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}

.task-header {
  justify-content: space-between;
}

.task-filters,
.task-controls {
  flex-wrap: wrap;
}

.task-filters .el-select,
.task-controls .el-select {
  width: 132px;
}

.task-list {
  display: grid;
  gap: 8px;
}

.task-list,
.gap-list {
  display: grid;
  gap: 8px;
}

.task-item,
.gap-item {
  width: 100%;
  text-align: left;
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #fff;
  padding: 8px;
  cursor: pointer;
}

.task-item.active,
.gap-item.active {
  border-color: #3b82f6;
  background: #eff6ff;
}

.task-item strong,
.task-item span,
.gap-item strong,
.gap-item span,
.task-sample strong,
.task-sample span,
.gap-sample strong,
.gap-sample span {
  display: block;
}

.task-item span,
.gap-item span,
.task-sample span,
.gap-sample span {
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.task-detail,
.gap-detail {
  margin-top: 12px;
}

.gap-meta {
  display: grid;
  gap: 4px;
  padding: 8px;
  margin-bottom: 10px;
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #f8fafc;
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.gap-triage-panel,
.gap-retest-panel,
.gap-history {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #f8fafc;
  padding: 8px;
  margin-bottom: 10px;
}

.safe-note {
  margin: 0 0 8px;
  color: var(--kb-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.triage-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 8px;
}

.history-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1.5fr;
  gap: 8px;
  color: var(--kb-text-secondary);
  font-size: 12px;
  padding: 3px 0;
}

.verification-lines {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 8px;
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.gap-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}

.gap-cards div {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 8px;
  background: #f8fafc;
}

.gap-cards span,
.gap-cards strong {
  display: block;
}

.gap-cards span {
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.gap-cards strong {
  color: var(--kb-text-primary);
  font-size: 18px;
  margin-top: 3px;
}

.verification-panel {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  background: #f8fafc;
  padding: 8px;
  margin-bottom: 10px;
}

.verification-line {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  padding: 3px 0;
}

.verification-line span {
  color: var(--kb-text-secondary);
}

.verification-line strong {
  color: var(--kb-text-primary);
}

.task-detail .el-input,
.gap-detail .el-input {
  margin-bottom: 8px;
}

.task-samples {
  margin-top: 10px;
}

.task-failure-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.task-sample,
.gap-sample,
.gap-draft {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 8px;
  background: #f8fafc;
  margin-bottom: 8px;
}

.task-sample p,
.gap-sample p {
  margin: 4px 0 0;
  line-height: 1.5;
  white-space: pre-wrap;
}

.gap-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.draft-fields {
  display: grid;
  gap: 4px;
  margin: 6px 0;
  color: var(--kb-text-secondary);
  font-size: 12px;
}

.gap-review-box,
.gap-publish-queue,
.queue-item {
  border: 1px solid var(--kb-border);
  border-radius: 8px;
  padding: 8px;
  background: #f8fafc;
  margin-bottom: 8px;
}

.queue-toolbar {
  display: grid;
  grid-template-columns: 140px minmax(0, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.queue-summary,
.queue-item span {
  display: block;
  color: var(--kb-text-secondary);
  font-size: 12px;
  margin-top: 3px;
}

.gap-reject-input {
  margin-top: 4px;
}

.gap-drafts {
  margin-top: 10px;
}

.fix-item {
  margin-bottom: 8px;
}

.fix-item strong,
.fix-item span {
  display: block;
}

pre {
  max-height: 300px;
  overflow: auto;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
}

.review-actions {
  margin-top: 10px;
}
</style>



