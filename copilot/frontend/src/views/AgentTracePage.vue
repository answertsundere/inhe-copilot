<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Aim, Key, Setting, Reading, Lock, ChatLineRound } from '@element-plus/icons-vue'
import { getTraces, getTrace, getTraceStats } from '../api/trace'

const loading = ref(false)
const detailLoading = ref(false)
const traces = ref<any[]>([])
const stats = ref<any>({})
const drawerVisible = ref(false)
const currentTrace = ref<any>(null)

const filters = reactive({
  conversation_id: '',
  intent: '',
  date_range: null as string[] | null,
  page: 1,
  page_size: 20,
})

const statsLoading = ref(false)

async function fetchTraces() {
  loading.value = true
  try {
    const { data } = await getTraces(filters)
    traces.value = data.items ?? data ?? []
  } catch {
    ElMessage.error('加载轨迹列表失败')
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  statsLoading.value = true
  try {
    const { data } = await getTraceStats()
    stats.value = data ?? {}
  } catch {
    // stats are non-critical, fail silently
  } finally {
    statsLoading.value = false
  }
}

async function openDetail(id: number) {
  detailLoading.value = true
  drawerVisible.value = true
  try {
    const { data } = await getTrace(id)
    currentTrace.value = data
  } catch {
    ElMessage.error('加载轨迹详情失败')
  } finally {
    detailLoading.value = false
  }
}

function nodeColor(status?: string) {
  if (status === 'passed') return '#67c23a'
  if (status === 'warning') return '#e6a23c'
  if (status === 'failed') return '#f56c6c'
  return '#409eff'
}

const avgConfidence = computed(() => stats.value.avg_confidence?.toFixed(1) ?? '--')
const guardPassRate = computed(() => stats.value.guard_pass_rate != null ? (stats.value.guard_pass_rate * 100).toFixed(1) + '%' : '--')
const avgDuration = computed(() => stats.value.avg_duration != null ? stats.value.avg_duration.toFixed(0) + 'ms' : '--')

function onDateRangeChange(val: any) {
  if (val) {
    filters.date_range = val.map((d: Date) => d.toISOString().slice(0, 10))
  } else {
    filters.date_range = null
  }
}

onMounted(() => {
  fetchTraces()
  fetchStats()
})
</script>

<template>
  <div class="trace-page">
    <!-- Top bar -->
    <el-card shadow="never" class="filter-bar">
      <el-row :gutter="12" align="middle">
        <el-col :span="6">
          <el-input v-model="filters.conversation_id" placeholder="搜索会话 ID" clearable @clear="fetchTraces" @keyup.enter="fetchTraces">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </el-col>
        <el-col :span="5">
          <el-select v-model="filters.intent" placeholder="意图筛选" clearable @change="fetchTraces">
            <el-option label="退款咨询" value="refund" />
            <el-option label="物流查询" value="shipping" />
            <el-option label="产品咨询" value="product" />
            <el-option label="投诉" value="complaint" />
          </el-select>
        </el-col>
        <el-col :span="7">
          <el-date-picker type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" style="width: 100%" @change="onDateRangeChange" />
        </el-col>
        <el-col :span="3">
          <el-button type="primary" @click="fetchTraces">搜索</el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- Stats bar -->
    <el-row :gutter="16" class="stats-bar" v-loading="statsLoading">
      <el-col :span="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ avgConfidence }}</div>
          <div class="stat-label">平均置信度</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ guardPassRate }}</div>
          <div class="stat-label">Guard 通过率</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ avgDuration }}</div>
          <div class="stat-label">平均耗时</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Trace list -->
    <div v-loading="loading" class="trace-list">
      <el-card v-for="t in traces" :key="t.id" shadow="hover" class="trace-item" @click="openDetail(t.id)">
        <el-row :gutter="16" align="middle">
          <el-col :span="5">
            <span class="trace-id">{{ t.conversation_id }}</span>
          </el-col>
          <el-col :span="7">
            <div class="customer-preview">{{ t.customer_message?.slice(0, 60) }}{{ t.customer_message?.length > 60 ? '...' : '' }}</div>
          </el-col>
          <el-col :span="3">
            <el-tag size="small">{{ t.detected_intent }}</el-tag>
          </el-col>
          <el-col :span="3">
            <span class="confidence-value" :style="{ color: t.confidence >= 0.8 ? '#67c23a' : t.confidence >= 0.5 ? '#e6a23c' : '#f56c6c' }">
              {{ (t.confidence * 100).toFixed(0) }}%
            </span>
          </el-col>
          <el-col :span="2">
            <el-icon :size="20" :color="t.guard_passed ? '#67c23a' : '#f56c6c'">
              <component :is="t.guard_passed ? 'CircleCheck' : 'CircleClose'" />
            </el-icon>
          </el-col>
          <el-col :span="2">
            <span class="trace-duration">{{ t.total_duration_ms }}ms</span>
          </el-col>
          <el-col :span="2">
            <span class="trace-time">{{ t.created_at?.slice(5, 16) }}</span>
          </el-col>
        </el-row>
      </el-card>

      <el-empty v-if="!loading && traces.length === 0" description="暂无轨迹数据" />
    </div>

    <!-- Detail drawer -->
    <el-drawer v-model="drawerVisible" title="Agent 轨迹详情" size="620px" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="currentTrace">
          <el-timeline>
            <!-- Node 1: Customer input -->
            <el-timeline-item :timestamp="'客户输入'" placement="top" :hollow="false">
              <template #dot><el-icon :size="18" color="#409eff"><User /></el-icon></template>
              <el-card shadow="never" class="node-card">
                <p class="node-content">{{ currentTrace.customer_message }}</p>
              </el-card>
            </el-timeline-item>

            <!-- Node 2: Intent recognition -->
            <el-timeline-item timestamp="意图识别" placement="top">
              <template #dot><el-icon :size="18" color="#409eff"><Aim /></el-icon></template>
              <el-card shadow="never" class="node-card">
                <el-row :gutter="12" align="middle">
                  <el-col :span="8"><el-tag>{{ currentTrace.detected_intent }}</el-tag></el-col>
                  <el-col :span="16">
                    <el-progress :percentage="Math.round((currentTrace.confidence ?? 0) * 100)" :stroke-width="14" :color="currentTrace.confidence >= 0.8 ? '#67c23a' : '#e6a23c'" />
                  </el-col>
                </el-row>
              </el-card>
            </el-timeline-item>

            <!-- Node 3: Slot extraction -->
            <el-timeline-item v-if="currentTrace.slots" timestamp="槽位提取" placement="top">
              <template #dot><el-icon :size="18" color="#409eff"><Key /></el-icon></template>
              <el-card shadow="never" class="node-card">
                <el-table :data="Object.entries(currentTrace.slots).map(([k, v]) => ({ key: k, value: v }))" size="small" border>
                  <el-table-column prop="key" label="槽位" width="140" />
                  <el-table-column prop="value" label="值" />
                </el-table>
              </el-card>
            </el-timeline-item>

            <!-- Node 4: Tool calls -->
            <el-timeline-item v-if="currentTrace.tool_calls?.length" timestamp="工具调用" placement="top">
              <template #dot><el-icon :size="18" color="#409eff"><Setting /></el-icon></template>
              <el-card shadow="never" class="node-card">
                <el-collapse>
                  <el-collapse-item v-for="(tool, i) in currentTrace.tool_calls" :key="i" :title="tool.name || `工具 ${Number(i) + 1}`">
                    <p class="tool-label">输入：</p>
                    <pre class="tool-data">{{ JSON.stringify(tool.input, null, 2) }}</pre>
                    <p class="tool-label">输出：</p>
                    <pre class="tool-data">{{ JSON.stringify(tool.output, null, 2) }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </el-card>
            </el-timeline-item>

            <!-- Node 5: Knowledge retrieval -->
            <el-timeline-item v-if="currentTrace.used_knowledge_ids?.length" timestamp="知识检索" placement="top">
              <template #dot><el-icon :size="18" color="#409eff"><Reading /></el-icon></template>
              <el-card shadow="never" class="node-card">
                <el-tag v-for="kid in currentTrace.used_knowledge_ids" :key="kid" size="small" style="margin: 2px">{{ kid }}</el-tag>
              </el-card>
            </el-timeline-item>

            <!-- Node 6: Output Guard -->
            <el-timeline-item timestamp="Output Guard" placement="top">
              <template #dot>
                <el-icon :size="18" :color="nodeColor(currentTrace.guard_passed ? 'passed' : (currentTrace.guard_warnings?.length ? 'warning' : 'failed'))">
                  <Lock />
                </el-icon>
              </template>
              <el-card shadow="never" class="node-card" :style="{ borderColor: nodeColor(currentTrace.guard_passed ? 'passed' : (currentTrace.guard_warnings?.length ? 'warning' : 'failed')) }">
                <el-tag :type="currentTrace.guard_passed ? 'success' : 'danger'" size="small">
                  {{ currentTrace.guard_passed ? '通过' : '未通过' }}
                </el-tag>
                <div v-if="currentTrace.guard_warnings?.length" style="margin-top: 8px">
                  <el-alert v-for="(w, i) in currentTrace.guard_warnings" :key="i" :title="w" type="warning" :closable="false" show-icon style="margin-bottom: 4px" />
                </div>
              </el-card>
            </el-timeline-item>

            <!-- Node 7: Final reply -->
            <el-timeline-item timestamp="最终回复" placement="top">
              <template #dot><el-icon :size="18" color="#409eff"><ChatLineRound /></el-icon></template>
              <el-card shadow="never" class="node-card">
                <p class="node-content">{{ currentTrace.final_reply_preview }}</p>
              </el-card>
            </el-timeline-item>
          </el-timeline>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.filter-bar { margin-bottom: 16px }
.filter-bar :deep(.el-card__body) { padding: 12px 16px }
.stats-bar { margin-bottom: 16px }
.stat-card { text-align: center }
.stat-value { font-size: 28px; font-weight: 700; color: #409eff }
.stat-label { font-size: 13px; color: #909399; margin-top: 4px }
.trace-item { margin-bottom: 8px; cursor: pointer; transition: box-shadow 0.2s }
.trace-item:hover { box-shadow: 0 4px 12px rgba(0,0,0,.12) }
.trace-item :deep(.el-card__body) { padding: 10px 16px }
.trace-id { font-family: monospace; font-size: 13px; color: #303133 }
.customer-preview { font-size: 13px; color: #606266; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.confidence-value { font-weight: 600; font-size: 14px }
.trace-duration { font-size: 13px; color: #909399 }
.trace-time { font-size: 12px; color: #909399 }
.node-card { margin-bottom: 0 }
.node-card :deep(.el-card__body) { padding: 12px }
.node-content { margin: 0; white-space: pre-wrap; font-size: 14px; color: #303133 }
.tool-label { font-size: 12px; color: #909399; margin: 4px 0 2px }
.tool-data { background: #f5f7fa; padding: 8px; border-radius: 4px; font-size: 12px; margin: 0 0 8px; white-space: pre-wrap; word-break: break-all }
</style>
