<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getHealthReport, getHealthIssues } from '../api/health'

const router = useRouter()
const loading = ref(false)
const checking = ref(false)
const report = ref<any>({})
const issues = ref<any[]>([])

const severityFilter = ref('')
const typeFilter = ref('')

async function fetchReport() {
  loading.value = true
  try {
    const { data } = await getHealthReport()
    report.value = data ?? {}
  } catch {
    ElMessage.error('加载健康报告失败')
  } finally {
    loading.value = false
  }
}

async function fetchIssues() {
  try {
    const params: Record<string, any> = {}
    if (severityFilter.value) params.severity = severityFilter.value
    if (typeFilter.value) params.issue_type = typeFilter.value
    const { data } = await getHealthIssues(params)
    issues.value = data.items ?? data ?? []
  } catch {
    ElMessage.error('加载问题列表失败')
  }
}

async function recheck() {
  checking.value = true
  try {
    await fetchReport()
    await fetchIssues()
    ElMessage.success('健康检查完成')
  } catch {
    ElMessage.error('健康检查失败')
  } finally {
    checking.value = false
  }
}

function navigateToFix(row: any) {
  const routeMap: Record<string, string> = {
    sop: '/sop',
    case: '/cases',
    product: '/products',
    qa: '/qa',
  }
  const target = routeMap[row.target_type] ?? '/'
  router.push(target)
}

function onFilterChange() {
  fetchIssues()
}

const healthScore = computed(() => report.value.score ?? 0)
const scoreColor = computed(() => {
  if (healthScore.value >= 80) return '#67c23a'
  if (healthScore.value >= 50) return '#e6a23c'
  return '#f56c6c'
})
const scoreStatus = computed<'success' | 'warning' | 'exception'>(() => {
  if (healthScore.value >= 80) return 'success'
  if (healthScore.value >= 50) return 'warning'
  return 'exception'
})

const highCount = computed(() => issues.value.filter((i: any) => i.severity === 'high').length)
const mediumCount = computed(() => issues.value.filter((i: any) => i.severity === 'medium').length)
const lowCount = computed(() => issues.value.filter((i: any) => i.severity === 'low').length)

const issueTypes = computed(() => {
  const types = new Set(issues.value.map((i: any) => i.issue_type))
  return Array.from(types)
})

function severityTagType(s: string) {
  if (s === 'high') return 'danger'
  if (s === 'medium') return 'warning'
  return 'info'
}

onMounted(() => {
  fetchReport()
  fetchIssues()
})
</script>

<template>
  <div class="health-page" v-loading="loading">
    <!-- Health score -->
    <div class="score-section">
      <el-progress
        type="circle"
        :percentage="healthScore"
        :width="180"
        :stroke-width="14"
        :color="scoreColor"
        :status="scoreStatus"
      >
        <template #default>
          <div class="score-inner">
            <div class="score-number" :style="{ color: scoreColor }">{{ healthScore }}</div>
            <div class="score-label">健康评分</div>
          </div>
        </template>
      </el-progress>
    </div>

    <!-- Stats row -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ issues.length }}</div>
          <div class="stat-label">问题总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card danger">
          <div class="stat-value">{{ highCount }}</div>
          <div class="stat-label">高严重度</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card warning">
          <div class="stat-value">{{ mediumCount }}</div>
          <div class="stat-label">中严重度</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card info">
          <div class="stat-value">{{ lowCount }}</div>
          <div class="stat-label">低严重度</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Filters -->
    <el-card shadow="never" class="filter-bar">
      <el-row :gutter="12" align="middle">
        <el-col :span="6">
          <el-select v-model="severityFilter" placeholder="严重程度" clearable @change="onFilterChange">
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-select v-model="typeFilter" placeholder="问题类型" clearable @change="onFilterChange">
            <el-option v-for="t in issueTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-col>
      </el-row>
    </el-card>

    <!-- Issue table -->
    <el-card shadow="never" class="table-card">
      <el-table :data="issues" stripe row-key="id" style="width: 100%">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-content">
              <p><strong>详细信息：</strong>{{ row.details || row.message }}</p>
              <p v-if="row.suggestion"><strong>修复建议：</strong>{{ row.suggestion }}</p>
              <p v-if="row.target_id"><strong>目标 ID：</strong>{{ row.target_id }}</p>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="严重度" width="100" prop="severity">
          <template #default="{ row }">
            <el-tag :type="severityTagType(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="问题类型" width="160" prop="issue_type" />
        <el-table-column label="目标" width="180">
          <template #default="{ row }">
            <span>{{ row.target_type }}</span>
            <el-tag v-if="row.target_id" size="small" type="info" style="margin-left: 4px">{{ row.target_id }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="描述" prop="message" show-overflow-tooltip />
        <el-table-column label="建议" prop="suggestion" show-overflow-tooltip width="200" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click.stop="navigateToFix(row)">去修复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Recheck button -->
    <div class="recheck-bar">
      <el-button type="primary" :loading="checking" @click="recheck">
        <el-icon v-if="!checking"><Refresh /></el-icon>
        重新检查
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.health-page { max-width: 1200px }
.score-section { text-align: center; padding: 24px 0 16px }
.score-inner { text-align: center }
.score-number { font-size: 42px; font-weight: 700; line-height: 1 }
.score-label { font-size: 13px; color: #909399; margin-top: 4px }
.stats-row { margin-bottom: 16px }
.stat-card { text-align: center; border-top: 3px solid #409eff }
.stat-card.danger { border-top-color: #f56c6c }
.stat-card.warning { border-top-color: #e6a23c }
.stat-card.info { border-top-color: #909399 }
.stat-value { font-size: 28px; font-weight: 700; color: #303133 }
.stat-label { font-size: 13px; color: #909399; margin-top: 4px }
.filter-bar { margin-bottom: 16px }
.filter-bar :deep(.el-card__body) { padding: 12px 16px }
.table-card { margin-bottom: 16px }
.expand-content { padding: 12px 24px; font-size: 13px; color: #606266 }
.expand-content p { margin: 4px 0 }
.recheck-bar { text-align: center; padding: 8px 0 }
</style>
