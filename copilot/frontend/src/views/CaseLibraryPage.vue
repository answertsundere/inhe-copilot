<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getCases, getCase, createCase, updateCase } from '../api/case'
import RiskBadge from '../components/common/RiskBadge.vue'

const loading = ref(false)
const detailLoading = ref(false)
const cases = ref<any[]>([])
const total = ref(0)
const drawerVisible = ref(false)
const editMode = ref(false)

const filters = reactive({
  scenario: '',
  category_l1: '',
  keyword: '',
  page: 1,
  page_size: 20,
})

const currentCase = ref<any>(null)
const editForm = reactive<any>({})

async function fetchCases() {
  loading.value = true
  try {
    const { data } = await getCases(filters)
    cases.value = data.items ?? data ?? []
    total.value = data.total ?? cases.value.length
  } catch {
    ElMessage.error('加载案例列表失败')
  } finally {
    loading.value = false
  }
}

async function openDetail(id: number) {
  detailLoading.value = true
  drawerVisible.value = true
  editMode.value = false
  try {
    const { data } = await getCase(id)
    currentCase.value = data
    Object.assign(editForm, data)
  } catch {
    ElMessage.error('加载案例详情失败')
  } finally {
    detailLoading.value = false
  }
}

function startEdit() {
  editMode.value = true
  Object.assign(editForm, currentCase.value)
}

function cancelEdit() {
  editMode.value = false
}

async function saveCase() {
  try {
    if (currentCase.value) {
      await updateCase(currentCase.value.id, editForm)
    } else {
      await createCase(editForm)
    }
    ElMessage.success('保存成功')
    editMode.value = false
    fetchCases()
  } catch {
    ElMessage.error('保存失败')
  }
}

function openCreate() {
  currentCase.value = null
  editMode.value = true
  Object.assign(editForm, {
    case_code: '', scenario: '', risk_level: 'medium', category_l1: '',
    customer_dialogue: '', correct_reply: '', wrong_reply: '',
    reply_quality_score: 80, wrong_reply_score: 30, supervisor_comment: '',
    tags: [], final_result: '',
  })
  drawerVisible.value = true
}

function resetFilters() {
  filters.scenario = ''
  filters.category_l1 = ''
  filters.keyword = ''
  filters.page = 1
  fetchCases()
}

onMounted(fetchCases)
</script>

<template>
  <div class="case-page">
    <!-- Top bar -->
    <el-card shadow="never" class="filter-bar">
      <el-row :gutter="12" align="middle">
        <el-col :span="5">
          <el-select v-model="filters.scenario" placeholder="场景筛选" clearable @change="fetchCases">
            <el-option label="退款" value="refund" />
            <el-option label="投诉" value="complaint" />
            <el-option label="物流" value="shipping" />
            <el-option label="产品" value="product" />
          </el-select>
        </el-col>
        <el-col :span="5">
          <el-select v-model="filters.category_l1" placeholder="分类筛选" clearable @change="fetchCases">
            <el-option label="优秀案例" value="excellent" />
            <el-option label="典型错误" value="typical_error" />
            <el-option label="培训案例" value="training" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-button type="primary" @click="openCreate">+ 新建案例</el-button>
        </el-col>
        <el-col :span="6">
          <el-input v-model="filters.keyword" placeholder="搜索案例编号 / 内容" clearable @clear="fetchCases" @keyup.enter="fetchCases">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </el-col>
        <el-col :span="4">
          <el-button @click="resetFilters">重置</el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- Case list -->
    <div v-loading="loading">
      <el-card v-for="c in cases" :key="c.id" shadow="hover" class="case-card" @click="openDetail(c.id)">
        <!-- Header -->
        <div class="case-header">
          <span class="case-code">{{ c.case_code }}</span>
          <el-tag size="small">{{ c.scenario }}</el-tag>
          <RiskBadge :level="c.risk_level" />
          <el-tag v-for="tag in (c.tags || []).slice(0, 3)" :key="tag" size="small" type="info" style="margin-left: 4px">{{ tag }}</el-tag>
        </div>

        <el-row :gutter="16" class="case-body">
          <!-- Customer quote -->
          <el-col :span="6">
            <div class="quote-block">
              <p class="quote-label">客户原话</p>
              <blockquote class="customer-quote">{{ c.customer_dialogue }}</blockquote>
            </div>
          </el-col>

          <!-- Reply comparison -->
          <el-col :span="18">
            <el-row :gutter="12">
              <el-col :span="12">
                <div class="reply-panel correct-panel">
                  <div class="panel-header">
                    <span>正确回复</span>
                    <el-tag type="success" size="small">{{ c.reply_quality_score }}分</el-tag>
                  </div>
                  <div class="panel-content">{{ c.correct_reply }}</div>
                </div>
              </el-col>
              <el-col :span="12">
                <div class="reply-panel wrong-panel">
                  <div class="panel-header">
                    <span>错误回复</span>
                    <el-tag type="danger" size="small">{{ c.wrong_reply_score }}分</el-tag>
                  </div>
                  <div class="panel-content">{{ c.wrong_reply }}</div>
                </div>
              </el-col>
            </el-row>
          </el-col>
        </el-row>

        <!-- Footer -->
        <div class="case-footer">
          <span v-if="c.supervisor_comment" class="comment-text">
            <em>主管点评：{{ c.supervisor_comment }}</em>
          </span>
          <el-tag v-if="c.final_result" size="small" :type="c.final_result === 'resolved' ? 'success' : 'warning'" style="margin-left: 12px">
            {{ c.final_result === 'resolved' ? '已解决' : c.final_result }}
          </el-tag>
        </div>
      </el-card>

      <el-empty v-if="!loading && cases.length === 0" description="暂无案例数据" />
    </div>

    <!-- Detail / Edit drawer -->
    <el-drawer v-model="drawerVisible" :title="editMode ? (currentCase ? '编辑案例' : '新建案例') : '案例详情'" size="640px" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="!editMode && currentCase">
          <el-descriptions :column="2" border style="margin-bottom: 20px">
            <el-descriptions-item label="案例编号">{{ currentCase.case_code }}</el-descriptions-item>
            <el-descriptions-item label="场景">{{ currentCase.scenario }}</el-descriptions-item>
            <el-descriptions-item label="风险等级"><RiskBadge :level="currentCase.risk_level" /></el-descriptions-item>
            <el-descriptions-item label="分类">{{ currentCase.category_l1 }}</el-descriptions-item>
          </el-descriptions>

          <h4>客户原话</h4>
          <el-card shadow="never" class="detail-block">{{ currentCase.customer_dialogue }}</el-card>

          <el-row :gutter="16" style="margin-top: 16px">
            <el-col :span="12">
              <h4>正确回复 <el-tag type="success" size="small">{{ currentCase.reply_quality_score }}分</el-tag></h4>
              <el-card shadow="never" class="detail-block correct-border">{{ currentCase.correct_reply }}</el-card>
            </el-col>
            <el-col :span="12">
              <h4>错误回复 <el-tag type="danger" size="small">{{ currentCase.wrong_reply_score }}分</el-tag></h4>
              <el-card shadow="never" class="detail-block wrong-border">{{ currentCase.wrong_reply }}</el-card>
            </el-col>
          </el-row>

          <div v-if="currentCase.supervisor_comment" style="margin-top: 16px">
            <h4>主管点评</h4>
            <p class="comment-text"><em>{{ currentCase.supervisor_comment }}</em></p>
          </div>

          <div style="margin-top: 24px; text-align: right">
            <el-button type="primary" @click="startEdit">编辑</el-button>
          </div>
        </template>

        <!-- Edit form -->
        <template v-if="editMode">
          <el-form label-position="top" :model="editForm">
            <el-form-item label="案例编号"><el-input v-model="editForm.case_code" /></el-form-item>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="场景">
                  <el-select v-model="editForm.scenario" style="width: 100%">
                    <el-option label="退款" value="refund" /><el-option label="投诉" value="complaint" />
                    <el-option label="物流" value="shipping" /><el-option label="产品" value="product" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="风险等级">
                  <el-select v-model="editForm.risk_level" style="width: 100%">
                    <el-option label="低" value="low" /><el-option label="中" value="medium" />
                    <el-option label="高" value="high" /><el-option label="极高" value="critical" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="客户原话"><el-input v-model="editForm.customer_dialogue" type="textarea" :rows="3" /></el-form-item>
            <el-form-item label="正确回复"><el-input v-model="editForm.correct_reply" type="textarea" :rows="3" /></el-form-item>
            <el-form-item label="错误回复"><el-input v-model="editForm.wrong_reply" type="textarea" :rows="3" /></el-form-item>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="正确回复评分">{{ editForm.reply_quality_score }}
                  <el-slider v-model="editForm.reply_quality_score" :min="0" :max="100" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="错误回复评分">{{ editForm.wrong_reply_score }}
                  <el-slider v-model="editForm.wrong_reply_score" :min="0" :max="100" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="主管点评"><el-input v-model="editForm.supervisor_comment" type="textarea" :rows="2" /></el-form-item>
            <el-form-item label="标签（逗号分隔）"><el-input v-model="editForm.tagsText" placeholder="退款,态度差,超时" /></el-form-item>
          </el-form>
          <div style="text-align: right">
            <el-button @click="cancelEdit">取消</el-button>
            <el-button type="primary" @click="saveCase">{{ currentCase ? '保存' : '创建' }}</el-button>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.filter-bar { margin-bottom: 16px }
.filter-bar :deep(.el-card__body) { padding: 12px 16px }
.case-card { margin-bottom: 16px; cursor: pointer; transition: box-shadow 0.2s }
.case-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.12) }
.case-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px }
.case-code { font-weight: 600; color: #303133 }
.case-body { margin-bottom: 12px }
.quote-block { height: 100% }
.quote-label { font-size: 12px; color: #909399; margin: 0 0 4px }
.customer-quote { margin: 0; padding: 10px; background: #f5f7fa; border-left: 3px solid #409eff; border-radius: 0 4px 4px 0; font-size: 13px; color: #606266; white-space: pre-wrap }
.reply-panel { border-radius: 6px; padding: 0; height: 100% }
.correct-panel { border: 2px solid #67c23a; border-radius: 6px; padding: 10px }
.wrong-panel { border: 2px solid #f56c6c; border-radius: 6px; padding: 10px }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-weight: 600; font-size: 13px }
.panel-content { font-size: 13px; color: #606266; white-space: pre-wrap; max-height: 80px; overflow: hidden; text-overflow: ellipsis }
.case-footer { display: flex; align-items: center; border-top: 1px solid #ebeef5; padding-top: 8px }
.comment-text { font-size: 13px; color: #909399 }
.detail-block { background: #f5f7fa; padding: 12px; white-space: pre-wrap; font-size: 14px }
.correct-border { border-left: 3px solid #67c23a }
.wrong-border { border-left: 3px solid #f56c6c }
h4 { color: #303133; margin: 0 0 8px; font-size: 14px }
</style>
