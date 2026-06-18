<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getMediaAssets } from '../../api/media'

const props = defineProps<{
  product: any
  qaList?: any[]
}>()

const question = ref('')
const testing = ref(false)
const result = ref<any>(null)

const sampleQuestions = [
  '有味道吗？',
  '能放卧室吗？',
  '尺寸多大？',
  '可以拆卸吗？',
  '有安装视频吗？',
]

const facts = computed(() => {
  const specs = props.product?.specs || {}
  return [
    { type: '尺寸', key: 'size', answer: specs.size },
    { type: '承重', key: 'load_capacity', answer: specs.load_capacity },
    { type: '材质', key: 'material', answer: specs.material },
    { type: '可拆卸', key: 'detachable', answer: specs.detachable },
    { type: '安装', key: 'install_method', answer: specs.install_method },
    { type: '配件', key: 'accessories', answer: specs.accessories },
    { type: '气味', key: 'odor_note', answer: specs.odor_note },
    { type: '清洁保养', key: 'cleaning', answer: specs.cleaning },
    { type: '适用场景', key: 'age_range', answer: specs.age_range },
    { type: '安全', key: 'pinch_safety', answer: specs.pinch_safety },
    { type: '证书', key: 'certification_report', answer: specs.certification_report },
  ].filter((f) => f.answer && String(f.answer).trim() && String(f.answer) !== '详见商品详情页')
})

async function runTest() {
  if (!question.value.trim()) {
    ElMessage.warning('请输入测试问题')
    return
  }
  testing.value = true
  result.value = null

  try {
    const q = question.value.trim().toLowerCase()
    const matchedFacts: any[] = []
    const matchedQA: any[] = []
    const matchedMedia: any[] = []

    // 匹配商品事实
    facts.value.forEach((fact) => {
      if (q.includes(fact.type) || q.includes(getKeyword(fact.key))) {
        matchedFacts.push(fact)
      }
    })

    // 匹配 QA
    const qaList = props.qaList || []
    qaList.forEach((qa) => {
      const text = `${qa.question || ''} ${qa.answer || ''}`.toLowerCase()
      const intent = (qa.intent || '').toLowerCase()
      if (text.includes(q) || q.includes(intent) || intent.includes(q)) {
        matchedQA.push(qa)
      }
    })

    // 匹配素材
    if (props.product?.id) {
      try {
        const { data } = await getMediaAssets({ product_id: props.product.id, limit: 50 })
        const assets = data.items || []
        assets.forEach((asset: any) => {
          const scenarios = (asset.source_raw?.answer_scenarios || asset.scene_tags || []).map((s: string) => s.toLowerCase())
          const purpose = (asset.source_raw?.media_purpose || asset.asset_type || '').toLowerCase()
          if (scenarios.some((s: string) => q.includes(s) || s.includes(q)) || q.includes(purpose)) {
            matchedMedia.push(asset)
          }
        })
      } catch {
        // ignore
      }
    }

    const hasHighRisk = matchedQA.some((qa) => ['high', 'critical'].includes(qa.risk_level))
    const canAutoSend = !hasHighRisk && matchedFacts.length > 0 && props.product?.status === 'published'

    result.value = {
      reply: buildReply(question.value, matchedFacts, matchedQA),
      matched_facts: matchedFacts.slice(0, 3),
      matched_qa: matchedQA.slice(0, 3),
      matched_media: matchedMedia.slice(0, 3),
      can_auto_send: canAutoSend,
      need_human_review: hasHighRisk || matchedQA.some((qa) => qa.human_review),
      failure_reason: canAutoSend ? '' : hasHighRisk ? '命中高风险问答' : '未找到明确商品事实或商品未发布',
    }
  } finally {
    testing.value = false
  }
}

function getKeyword(key: string) {
  const map: Record<string, string> = {
    size: '多大',
    load_capacity: '承重',
    material: '材质',
    detachable: '拆',
    install_method: '安装',
    accessories: '配件',
    odor_note: '味道',
    cleaning: '清洁',
    age_range: '年龄',
    pinch_safety: '安全',
    certification_report: '证书',
  }
  return map[key] || key
}

function buildReply(q: string, facts: any[], qa: any[]) {
  if (qa.length) return qa[0].answer
  if (facts.length) {
    const name = props.product?.product_name || '这款商品'
    const lines = facts.map((f) => `${f.type}：${f.answer}`)
    return `关于「${name}」的${q}，\n${lines.join('；')}。\n具体以下单页面为准。`
  }
  return '抱歉，暂未找到相关资料，已转人工处理。'
}

function setQuestion(q: string) {
  question.value = q
  runTest()
}
</script>

<template>
  <div class="agent-test-panel">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="资料命中预检"
      description="输入买家问题，检查当前商品资料（商品事实、客户问法、素材标签）是否可能命中。本工具不调用真实 Agent，仅用于资料维护阶段的快速自查。"
      style="margin-bottom: 16px"
    />

    <div class="quick-questions">
      <span class="quick-label">快捷预检：</span>
      <el-button
        v-for="q in sampleQuestions"
        :key="q"
        size="small"
        text
        @click="setQuestion(q)"
      >
        {{ q }}
      </el-button>
    </div>

    <div class="test-input-row">
      <el-input v-model="question" placeholder="输入买家问题，例如：尺寸多大？" clearable @keyup.enter="runTest" />
      <el-button type="primary" :loading="testing" @click="runTest">运行预检</el-button>
    </div>

    <div v-if="result" class="test-result">
      <div class="result-header">
        <div class="result-title">预检结果</div>
        <div class="result-badges">
          <el-tag :type="result.can_auto_send ? 'success' : 'warning'" size="small">
            {{ result.can_auto_send ? '资料可命中' : '资料可能不足' }}
          </el-tag>
          <el-tag :type="result.need_human_review ? 'danger' : 'success'" size="small">
            {{ result.need_human_review ? '需人工审核' : '无需强制人工审核' }}
          </el-tag>
        </div>
      </div>
      <div class="reply-box">{{ result.reply }}</div>
      <div v-if="result.failure_reason" class="failure-reason">未命中原因：{{ result.failure_reason }}</div>

      <div class="hit-sections">
        <div v-if="result.matched_facts.length" class="hit-section">
          <div class="hit-title">命中商品事实（{{ result.matched_facts.length }}）</div>
          <div v-for="fact in result.matched_facts" :key="fact.key" class="hit-item">
            <span class="hit-type">{{ fact.type }}</span>
            <span class="hit-content">{{ fact.answer }}</span>
          </div>
        </div>
        <div v-if="result.matched_qa.length" class="hit-section">
          <div class="hit-title">命中问答（{{ result.matched_qa.length }}）</div>
          <div v-for="qa in result.matched_qa" :key="qa.id" class="hit-item">
            <span class="hit-type">Q</span>
            <span class="hit-content">{{ qa.question }}</span>
          </div>
        </div>
        <div v-if="result.matched_media.length" class="hit-section">
          <div class="hit-title">命中素材（{{ result.matched_media.length }}）</div>
          <div v-for="media in result.matched_media" :key="media.id" class="hit-item">
            <span class="hit-type">图</span>
            <span class="hit-content">{{ media.asset_title || media.asset_type }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.agent-test-panel {
  padding: 4px;
}
.quick-questions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.quick-label {
  font-size: 13px;
  color: var(--kb-text-secondary);
}
.test-input-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.test-input-row .el-input {
  flex: 1;
}
.test-result {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 16px;
  box-shadow: var(--kb-shadow-card);
}
.result-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.result-title {
  font-size: 15px;
  font-weight: 600;
}
.result-badges {
  display: flex;
  gap: 6px;
}
.reply-box {
  background: var(--kb-accent-subtle);
  color: var(--kb-text-primary);
  padding: 14px;
  border-radius: var(--kb-radius-md);
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.failure-reason {
  margin-top: 10px;
  font-size: 13px;
  color: var(--kb-danger-text);
}
.hit-sections {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 16px;
}
.hit-section {
  background: var(--kb-bg-hover);
  border-radius: var(--kb-radius-md);
  padding: 12px;
}
.hit-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  margin-bottom: 8px;
}
.hit-item {
  display: flex;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 6px;
}
.hit-type {
  flex-shrink: 0;
  color: var(--kb-accent);
  font-weight: 600;
}
.hit-content {
  color: var(--kb-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
</style>
