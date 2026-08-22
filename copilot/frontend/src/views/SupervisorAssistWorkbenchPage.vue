<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue'
import {
  ChatDotRound,
  CircleCheck,
  CopyDocument,
  Delete,
  DocumentChecked,
  MagicStick,
  RefreshRight,
  Setting,
  Timer,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  analyzeForSupervisor,
  buildAnalyzeRequest,
  readableAnalyzeError,
  type CandidateObservation,
  type ConversationTurn,
  type WorkbenchContext,
} from '../api/supervisorAssist'

interface ViewTurn {
  id: string
  role: 'customer' | 'agent' | 'error'
  text: string
  createdAt: string
  durationMs?: number
  observation?: CandidateObservation
  retryMessage?: string
}

interface WorkbenchShop {
  id: string
  name: string
  jstShopId: string
  orderLookupProvider: string
}

function loadConfiguredShops(): WorkbenchShop[] {
  const raw = String(import.meta.env.VITE_SUPERVISOR_SHOPS_JSON || '').trim()
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .map((item) => ({
        id: String(item?.id || '').trim(),
        name: String(item?.name || '').trim(),
        jstShopId: String(item?.jst_shop_id || '').trim(),
        orderLookupProvider: String(item?.order_lookup_provider || 'jst_standard').trim(),
      }))
      .filter((item) => item.id && item.name)
  } catch {
    return []
  }
}

const configuredShops = loadConfiguredShops()
const defaultShop = configuredShops[0] || {
  id: '', name: '', jstShopId: '', orderLookupProvider: 'jst_standard',
}

const context = reactive<WorkbenchContext>({
  shopId: defaultShop.id,
  shopName: defaultShop.name,
  jstShopId: defaultShop.jstShopId,
  orderLookupProvider: defaultShop.orderLookupProvider,
  productName: '',
  skuCode: '',
  iId: '',
  orderId: '',
  trackingNo: '',
})
const turns = ref<ViewTurn[]>([])
const draft = ref('')
const busy = ref(false)
const conversationId = ref(createConversationId())
const timeline = ref<HTMLElement>()
const showContext = ref(
  typeof window === 'undefined' || !window.matchMedia('(max-width: 760px)').matches,
)

const successfulReplies = computed(() => turns.value.filter((turn) => turn.role === 'agent').length)
const totalEvidence = computed(() => turns.value.reduce(
  (total, turn) => total + (turn.observation?.evidence.length || 0),
  0,
))

function createConversationId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `supervisor-${crypto.randomUUID()}`
  }
  return `supervisor-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function turnId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function nowLabel(): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date())
}

function canonicalHistory(): ConversationTurn[] {
  return turns.value
    .filter((turn) => turn.role === 'customer' || turn.role === 'agent')
    .map((turn) => ({
      role: turn.role === 'customer' ? 'customer' : 'agent',
      text: turn.text,
    }))
}

async function scrollToLatest() {
  await nextTick()
  if (timeline.value) timeline.value.scrollTop = timeline.value.scrollHeight
}

async function submitMessage(message = draft.value) {
  const normalized = message.trim()
  if (!normalized || busy.value) return

  const priorHistory = canonicalHistory()
  turns.value.push({ id: turnId(), role: 'customer', text: normalized, createdAt: nowLabel() })
  draft.value = ''
  busy.value = true
  await scrollToLatest()
  const startedAt = performance.now()

  try {
    const request = buildAnalyzeRequest(normalized, conversationId.value, priorHistory, context)
    const observation = await analyzeForSupervisor(request)
    turns.value.push({
      id: turnId(),
      role: 'agent',
      text: observation.reply,
      createdAt: nowLabel(),
      durationMs: Math.round(performance.now() - startedAt),
      observation,
    })
  } catch (error) {
    turns.value.push({
      id: turnId(),
      role: 'error',
      text: readableAnalyzeError(error),
      createdAt: nowLabel(),
      retryMessage: normalized,
    })
  } finally {
    busy.value = false
    await scrollToLatest()
  }
}

function resetConversation() {
  turns.value = []
  draft.value = ''
  conversationId.value = createConversationId()
  ElMessage.success('已开始新对话')
}

async function copyReply(text: string) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('候选回复已复制')
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submitMessage()
  }
}

function formatDuration(durationMs?: number): string {
  if (durationMs === undefined) return '-'
  return durationMs < 1000 ? `${durationMs} 毫秒` : `${(durationMs / 1000).toFixed(1)} 秒`
}

function evidenceTitle(evidence: CandidateObservation['evidence'][number], index: number): string {
  return evidence.attribute || evidence.factType || evidence.role || `证据 ${index + 1}`
}

function selectShop(shopId: string) {
  const selected = configuredShops.find((shop) => shop.id === shopId)
  context.shopName = selected?.name || ''
  context.jstShopId = selected?.jstShopId || ''
  context.orderLookupProvider = selected?.orderLookupProvider || 'jst_standard'
}
</script>

<template>
  <section class="assist-workbench" :class="{ 'context-hidden': !showContext }">
    <div class="conversation-panel">
      <div class="conversation-toolbar">
        <div class="session-state">
          <span class="live-dot" aria-hidden="true"></span>
          <strong>人工确认模式</strong>
          <span>{{ successfulReplies }} 条候选</span>
          <span>{{ totalEvidence }} 条证据</span>
        </div>
        <div class="toolbar-actions">
          <el-tooltip content="显示或隐藏商品与订单信息" placement="bottom">
            <el-button :icon="Setting" circle aria-label="显示或隐藏上下文" @click="showContext = !showContext" />
          </el-tooltip>
          <el-tooltip content="开始新对话" placement="bottom">
            <el-button :icon="Delete" circle aria-label="开始新对话" @click="resetConversation" />
          </el-tooltip>
        </div>
      </div>

      <div ref="timeline" class="conversation-timeline" aria-live="polite">
        <div v-if="turns.length === 0" class="empty-state">
          <el-icon><ChatDotRound /></el-icon>
          <strong>输入一条客户消息开始测试</strong>
          <span>后续追问会自动带上本页已有对话。</span>
        </div>

        <article v-for="turn in turns" :key="turn.id" class="turn-row" :class="`turn-${turn.role}`">
          <div class="turn-marker" aria-hidden="true">
            <span v-if="turn.role === 'customer'">客</span>
            <el-icon v-else-if="turn.role === 'agent'"><MagicStick /></el-icon>
            <el-icon v-else><Warning /></el-icon>
          </div>

          <div class="turn-content">
            <header>
              <strong>{{ turn.role === 'customer' ? '客户' : turn.role === 'agent' ? '候选回复' : '生成失败' }}</strong>
              <span>{{ turn.createdAt }}</span>
              <el-tooltip v-if="turn.role === 'agent'" content="复制候选回复" placement="top">
                <el-button
                  text
                  :icon="CopyDocument"
                  aria-label="复制候选回复"
                  @click="copyReply(turn.text)"
                />
              </el-tooltip>
            </header>

            <p class="turn-text">{{ turn.text }}</p>

            <div v-if="turn.observation" class="observation-strip">
              <span class="review-badge"><el-icon><CircleCheck /></el-icon>需人工确认</span>
              <span><el-icon><Timer /></el-icon>{{ formatDuration(turn.durationMs) }}</span>
              <span><el-icon><DocumentChecked /></el-icon>{{ turn.observation.evidence.length }} 条正式证据</span>
              <span v-if="turn.observation.riskLevel">风险：{{ turn.observation.riskLevel }}</span>
            </div>

            <el-collapse v-if="turn.observation" class="evidence-collapse">
              <el-collapse-item name="evidence">
                <template #title>
                  <span>查看本轮依据与审核状态</span>
                </template>
                <div v-if="turn.observation.evidence.length" class="evidence-list">
                  <div
                    v-for="(evidence, index) in turn.observation.evidence"
                    :key="evidence.uid || index"
                    class="evidence-row"
                  >
                    <strong>{{ evidenceTitle(evidence, index) }}</strong>
                    <span>{{ evidence.factType || '未标注事实类型' }}</span>
                    <span>{{ evidence.reviewStatus || '审核状态未返回' }}</span>
                    <code v-if="evidence.uid">{{ evidence.uid }}</code>
                  </div>
                </div>
                <p v-else class="empty-evidence">本轮未选中正式证据，候选回复不可直接发送。</p>
                <div v-if="turn.observation.reviewReasons.length" class="review-reasons">
                  <strong>需复核原因</strong>
                  <span v-for="reason in turn.observation.reviewReasons" :key="reason">{{ reason }}</span>
                </div>
                <p v-if="turn.observation.returnedCanSend" class="runtime-warning">
                  后端返回了可发送状态，但体验台仍不会执行发送。
                </p>
              </el-collapse-item>
            </el-collapse>

            <el-button
              v-if="turn.role === 'error' && turn.retryMessage"
              size="small"
              :icon="RefreshRight"
              :disabled="busy"
              @click="submitMessage(turn.retryMessage)"
            >
              重试这条消息
            </el-button>
          </div>
        </article>

        <div v-if="busy" class="thinking-row">
          <span></span><span></span><span></span>
          <em>正在生成候选回复</em>
        </div>
      </div>

      <div class="composer-bar">
        <el-input
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 6 }"
          maxlength="2000"
          resize="none"
          placeholder="输入客户现在问的问题"
          :disabled="busy"
          @keydown="handleComposerKeydown"
        />
        <el-button
          type="primary"
          :icon="MagicStick"
          :loading="busy"
          :disabled="!draft.trim()"
          @click="submitMessage()"
        >
          生成建议
        </el-button>
      </div>
    </div>

    <aside v-show="showContext" class="context-panel">
      <div class="context-heading">
        <div>
          <strong>当前上下文</strong>
          <span>只在本页对话中使用</span>
        </div>
        <span class="optional-label">选填</span>
      </div>

      <el-form label-position="top" class="context-form">
        <el-form-item label="店铺">
          <el-select
            v-model="context.shopId"
            placeholder="选择订单所属店铺"
            :disabled="configuredShops.length === 0"
            filterable
            @change="selectShop"
          >
            <el-option
              v-for="shop in configuredShops"
              :key="shop.id"
              :label="shop.name"
              :value="shop.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="商品标题">
          <el-input v-model="context.productName" placeholder="粘贴客户看到的商品标题" clearable />
        </el-form-item>
        <div class="two-column-fields">
          <el-form-item label="SKU 编码">
            <el-input v-model="context.skuCode" placeholder="内部 SKU" clearable />
          </el-form-item>
          <el-form-item label="商品 i_id">
            <el-input v-model="context.iId" placeholder="内部商品编号" clearable />
          </el-form-item>
        </div>
        <el-form-item label="订单号">
          <el-input v-model="context.orderId" placeholder="平台订单号" clearable />
        </el-form-item>
        <el-form-item label="物流单号">
          <el-input v-model="context.trackingNo" placeholder="需要查询物流时填写" clearable />
        </el-form-item>
      </el-form>

      <div class="boundary-note">
        <el-icon><Warning /></el-icon>
        <p><strong>不会自动发送</strong><span>体验台仅生成候选，发送前必须由坐席确认。</span></p>
      </div>
    </aside>
  </section>
</template>

<style scoped>
.assist-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 326px;
  height: calc(100vh - 132px);
  min-height: 560px;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgb(15 23 42 / 5%);
}

.assist-workbench.context-hidden {
  grid-template-columns: minmax(0, 1fr);
}

.conversation-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 0;
}

.conversation-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 48px;
  padding: 0 16px;
  border-bottom: 1px solid #e5eaf0;
}

.session-state,
.toolbar-actions,
.observation-strip {
  display: flex;
  align-items: center;
}

.session-state {
  gap: 12px;
  color: #64748b;
  font-size: 12px;
}

.session-state strong {
  color: #172033;
  font-size: 13px;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #16a34a;
  box-shadow: 0 0 0 3px #dcfce7;
}

.toolbar-actions {
  gap: 8px;
}

.conversation-timeline {
  min-height: 0;
  padding: 12px 22px 28px;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  color: #94a3b8;
  text-align: center;
}

.empty-state .el-icon {
  margin-bottom: 12px;
  color: #4f6af6;
  font-size: 32px;
}

.empty-state strong {
  margin-bottom: 5px;
  color: #334155;
  font-size: 15px;
}

.empty-state span {
  font-size: 13px;
}

.turn-row {
  position: relative;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 12px;
  padding: 16px 0;
}

.turn-row + .turn-row {
  border-top: 1px solid #eef1f5;
}

.turn-marker {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: #eef1ff;
  color: #3f56d9;
  font-size: 13px;
  font-weight: 700;
}

.turn-agent .turn-marker {
  background: #e8f7ef;
  color: #15803d;
}

.turn-error .turn-marker {
  background: #fff1f2;
  color: #be123c;
}

.turn-content {
  min-width: 0;
}

.turn-content header {
  display: flex;
  align-items: center;
  min-height: 28px;
  gap: 10px;
}

.turn-content header strong {
  color: #172033;
  font-size: 13px;
}

.turn-content header span {
  color: #94a3b8;
  font-size: 12px;
}

.turn-content header .el-button {
  margin-left: auto;
}

.turn-text {
  margin: 4px 0 0;
  color: #1f2937;
  font-size: 15px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.turn-agent .turn-text {
  color: #111827;
}

.turn-error .turn-text {
  margin-bottom: 10px;
  color: #9f1239;
}

.observation-strip {
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 12px;
  color: #64748b;
  font-size: 12px;
}

.observation-strip > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.review-badge {
  padding: 3px 8px;
  border-radius: 4px;
  background: #fff7df;
  color: #8a5a00;
  font-weight: 600;
}

.evidence-collapse {
  margin-top: 8px;
  border-top: 0;
  border-bottom: 0;
}

.evidence-collapse :deep(.el-collapse-item__header) {
  height: 34px;
  border-bottom: 0;
  color: #475569;
  font-size: 12px;
}

.evidence-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
}

.evidence-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 4px;
}

.evidence-list {
  border-top: 1px solid #e5eaf0;
}

.evidence-row {
  display: grid;
  grid-template-columns: minmax(130px, 1.2fr) minmax(100px, 1fr) minmax(100px, 1fr);
  gap: 8px;
  padding: 9px 2px;
  border-bottom: 1px solid #eef1f5;
  color: #64748b;
  font-size: 12px;
}

.evidence-row strong {
  color: #334155;
}

.evidence-row code {
  grid-column: 1 / -1;
  color: #7c8799;
  font-size: 11px;
  overflow-wrap: anywhere;
}

.empty-evidence,
.runtime-warning {
  margin: 0;
  padding: 9px 10px;
  border-radius: 6px;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
}

.runtime-warning {
  margin-top: 8px;
  background: #fff1f2;
  color: #9f1239;
}

.review-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  font-size: 12px;
}

.review-reasons strong {
  width: 100%;
  color: #334155;
}

.review-reasons span {
  padding: 3px 7px;
  border: 1px solid #e5eaf0;
  border-radius: 4px;
  color: #64748b;
}

.thinking-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 16px 0 10px 46px;
  color: #64748b;
}

.thinking-row span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #4f6af6;
  animation: pulse 1.2s infinite ease-in-out;
}

.thinking-row span:nth-child(2) { animation-delay: 0.15s; }
.thinking-row span:nth-child(3) { animation-delay: 0.3s; }
.thinking-row em {
  margin-left: 6px;
  font-size: 12px;
  font-style: normal;
}

.composer-bar {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 14px 16px 24px;
  border-top: 1px solid #e5eaf0;
  background: #ffffff;
}

.composer-bar .el-button {
  align-self: stretch;
  min-width: 112px;
}

.context-panel {
  min-width: 0;
  padding: 18px;
  overflow-y: auto;
  background: #f8fafc;
  border-left: 1px solid #dbe2ea;
}

.context-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 18px;
}

.context-heading div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.context-heading strong {
  color: #172033;
  font-size: 14px;
}

.context-heading span {
  color: #7c8799;
  font-size: 12px;
}

.optional-label {
  padding: 2px 7px;
  border: 1px solid #d9e0e8;
  border-radius: 4px;
  background: #ffffff;
}

.context-form :deep(.el-form-item) {
  margin-bottom: 15px;
}

.context-form :deep(.el-form-item__label) {
  margin-bottom: 5px;
  color: #475569;
  font-size: 12px;
  line-height: 1.3;
}

.two-column-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.boundary-note {
  display: flex;
  gap: 9px;
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px solid #dbe2ea;
  color: #9a6700;
}

.boundary-note .el-icon {
  flex: 0 0 auto;
  margin-top: 2px;
}

.boundary-note p {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}

.boundary-note strong {
  color: #765000;
}

@keyframes pulse {
  0%, 70%, 100% { opacity: 0.3; transform: translateY(0); }
  35% { opacity: 1; transform: translateY(-2px); }
}

@media (prefers-reduced-motion: reduce) {
  .conversation-timeline { scroll-behavior: auto; }
  .thinking-row span { animation: none; }
}

@media (max-width: 1040px) {
  .assist-workbench {
    grid-template-columns: minmax(0, 1fr) 286px;
  }

  .two-column-fields {
    grid-template-columns: 1fr;
    gap: 0;
  }
}

@media (max-width: 760px) {
  .assist-workbench {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 104px);
    min-height: 500px;
  }

  .conversation-panel {
    flex: 1;
    min-height: 0;
  }

  .context-panel {
    order: -1;
    max-height: 42vh;
    border-left: 0;
    border-bottom: 1px solid #dbe2ea;
  }

  .session-state > span:not(.live-dot) {
    display: none;
  }

  .conversation-timeline {
    padding: 8px 12px 20px;
  }

  .turn-row {
    grid-template-columns: 30px minmax(0, 1fr);
    gap: 9px;
  }

  .turn-marker {
    width: 28px;
    height: 28px;
  }

  .turn-text {
    font-size: 14px;
  }

  .composer-bar {
    grid-template-columns: minmax(0, 1fr);
    padding: 10px;
  }

  .composer-bar .el-button {
    min-height: 38px;
  }

  .evidence-row {
    grid-template-columns: 1fr;
  }

  .evidence-row code {
    grid-column: auto;
  }
}
</style>
