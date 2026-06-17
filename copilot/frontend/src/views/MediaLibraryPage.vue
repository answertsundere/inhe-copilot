<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getMediaStats,
  getMediaAssets,
  approveMedia,
  rejectMedia,
  updateMedia,
  importDingtalkReport,
  batchUpdateMediaTags,
  ASSET_TYPE_LABELS,
  STATUS_LABELS,
  STATUS_TAG_TYPES,
  type MediaAsset,
  type MediaStats,
} from '../api/media'

const SCENE_TAG_OPTIONS = [
  '尺寸', '可拆卸', '安装', '配件', '包装清单', '证书/质检', '颜色外观', '材质',
  '商品咨询', '尺寸咨询', '安装咨询', '配件缺失',
]

const loading = ref(false)
const importing = ref(false)
const stats = ref<MediaStats>({ total: 0, pending_review: 0, approved: 0, rejected: 0, usable_for_agent: 0, by_type: {} })
const list = ref<MediaAsset[]>([])
const total = ref(0)

// 筛选
const filters = reactive({
  keyword: '',
  asset_type: '',
  status: '',
  usable_for_agent: '' as string,
})

// 分页
const page = ref(1)
const pageSize = ref(20)

// 批量标签
const selectedMedia = ref<MediaAsset[]>([])
const batchDialogVisible = ref(false)
const batchMode = ref<'add' | 'remove'>('add')
const batchTag = ref('')

// 编辑弹窗
const editVisible = ref(false)
const editing = ref<Partial<MediaAsset>>({})
const isSupervisor = computed(() => (localStorage.getItem('kb_user_role') || 'supervisor') !== 'operator')

const editingSceneTags = computed({
  get: () => (editing.value.scene_tags || []).join(', '),
  set: (v: string) => { editing.value.scene_tags = v.split(',').map((s) => s.trim()).filter(Boolean) },
})

async function fetchStats() {
  try {
    const { data } = await getMediaStats()
    stats.value = data
  } catch {
    ElMessage.error('加载素材统计失败')
  }
}

async function fetchList() {
  loading.value = true
  try {
    const params: Record<string, any> = {
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
    }
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.asset_type) params.asset_type = filters.asset_type
    if (filters.status) params.status = filters.status
    if (filters.usable_for_agent !== '') params.usable_for_agent = filters.usable_for_agent
    const { data } = await getMediaAssets(params)
    list.value = data.items ?? []
    total.value = data.total ?? 0
  } catch {
    ElMessage.error('加载素材列表失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  fetchList()
}

function onReset() {
  filters.keyword = ''
  filters.asset_type = ''
  filters.status = ''
  filters.usable_for_agent = ''
  page.value = 1
  fetchList()
}

async function onImport() {
  try {
    await ElMessageBox.confirm(
      '将从钉钉素材报告(data/dingtalk_media_report_v2.json)导入/更新素材。已审核素材不会被重置，是否继续？',
      '从钉钉素材报告导入',
      { confirmButtonText: '开始导入', cancelButtonText: '取消', type: 'info' },
    )
  } catch {
    return
  }
  importing.value = true
  try {
    const { data } = await importDingtalkReport()
    ElMessage.success(`导入完成：新增 ${data.stats?.new_assets ?? 0}，更新 ${data.stats?.updated_assets ?? 0}`)
    await fetchStats()
    await fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '导入失败')
  } finally {
    importing.value = false
  }
}

async function onRefreshFromDaily() {
  try {
    await ElMessageBox.confirm(
      '将从今日钉钉媒体报告(data/dingtalk_media_report_daily.json)导入/更新素材。已审核素材不会被重置，是否继续？',
      '刷新今日钉钉素材',
      { confirmButtonText: '开始刷新', cancelButtonText: '取消', type: 'info' },
    )
  } catch {
    return
  }
  importing.value = true
  try {
    const { data } = await importDingtalkReport('data/dingtalk_media_report_daily.json')
    ElMessage.success(`刷新完成：新增 ${data.stats?.new_assets ?? 0}，更新 ${data.stats?.updated_assets ?? 0}`)
    await fetchStats()
    await fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '刷新失败')
  } finally {
    importing.value = false
  }
}

function onSelectionChange(val: MediaAsset[]) {
  selectedMedia.value = val
}

function openBatchDialog(mode: 'add' | 'remove') {
  if (!isSupervisor.value) {
    ElMessage.warning('仅主管/管理员可批量操作')
    return
  }
  if (!selectedMedia.value.length) {
    ElMessage.warning('请先勾选要操作的素材')
    return
  }
  batchMode.value = mode
  batchTag.value = ''
  batchDialogVisible.value = true
}

async function applyBatchTag() {
  const tag = batchTag.value.trim()
  if (!tag) {
    ElMessage.warning('请选择或输入标签')
    return
  }
  const ids = selectedMedia.value.map((m) => m.id)
  const addTags = batchMode.value === 'add' ? [tag] : []
  const removeTags = batchMode.value === 'remove' ? [tag] : []
  try {
    const { data } = await batchUpdateMediaTags(ids, addTags, removeTags)
    ElMessage.success(`已${batchMode.value === 'add' ? '添加' : '移除'} ${data.updated} 条素材的标签`)
    batchDialogVisible.value = false
    selectedMedia.value = []
    await fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '批量操作失败')
  }
}

async function onApprove(row: MediaAsset) {
  try {
    await approveMedia(row.id)
    ElMessage.success('已审核通过，AI 可推荐此素材')
    await fetchStats()
    await fetchList()
  } catch {
    ElMessage.error('操作失败')
  }
}

async function onReject(row: MediaAsset) {
  try {
    await rejectMedia(row.id)
    ElMessage.success('已拒绝')
    await fetchStats()
    await fetchList()
  } catch {
    ElMessage.error('操作失败')
  }
}

function openEdit(row: MediaAsset) {
  editing.value = { ...row }
  editVisible.value = true
}

async function saveEdit() {
  try {
    const f: Record<string, any> = {
      asset_title: editing.value.asset_title,
      asset_type: editing.value.asset_type,
      asset_url: editing.value.asset_url,
      status: editing.value.status,
      usable_for_agent: editing.value.usable_for_agent,
      scene_tags: editing.value.scene_tags,
    }
    await updateMedia(editing.value.id!, f)
    ElMessage.success('已保存')
    editVisible.value = false
    await fetchStats()
    await fetchList()
  } catch {
    ElMessage.error('保存失败')
  }
}

function copyUrl(url: string) {
  navigator.clipboard?.writeText(url).then(
    () => ElMessage.success('链接已复制'),
    () => ElMessage.warning('复制失败，请手动复制'),
  )
}

onMounted(() => {
  fetchStats()
  fetchList()
})
</script>

<template>
  <div class="media-library">
    <!-- 概览卡片 -->
    <el-row :gutter="12" class="stat-row">
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num">{{ stats.total }}</div>
          <div class="stat-label">素材总数</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num warn">{{ stats.pending_review }}</div>
          <div class="stat-label">待审核</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num ok">{{ stats.approved }}</div>
          <div class="stat-label">已审核可用</div>
        </el-card>
      </el-col>
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num ok">{{ stats.usable_for_agent }}</div>
          <div class="stat-label">Agent 可推荐</div>
        </el-card>
      </el-col>
      <el-col v-for="(count, type) in stats.by_type" :key="type" :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-num">{{ count }}</div>
          <div class="stat-label">{{ ASSET_TYPE_LABELS[type] || type }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 工具栏 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <el-input
          v-model="filters.keyword"
          placeholder="商品名 / i_id / SKU / 标题"
          clearable
          style="width: 240px"
          @keyup.enter="onSearch"
        />
        <el-select v-model="filters.asset_type" placeholder="素材类型" clearable style="width: 160px" @change="onSearch">
          <el-option v-for="(label, key) in ASSET_TYPE_LABELS" :key="key" :label="label" :value="key" />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 140px" @change="onSearch">
          <el-option v-for="(label, key) in STATUS_LABELS" :key="key" :label="label" :value="key" />
        </el-select>
        <el-select v-model="filters.usable_for_agent" placeholder="是否可推荐" clearable style="width: 140px" @change="onSearch">
          <el-option label="可推荐" value="true" />
          <el-option label="不可推荐" value="false" />
        </el-select>
        <el-button type="primary" @click="onSearch">查询</el-button>
        <el-button @click="onReset">重置</el-button>
        <div class="toolbar-right">
          <el-button size="small" :disabled="!isSupervisor || !selectedMedia.length" @click="openBatchDialog('add')">批量添加标签</el-button>
          <el-button size="small" :disabled="!isSupervisor || !selectedMedia.length" @click="openBatchDialog('remove')">批量移除标签</el-button>
          <el-button type="success" :loading="importing" :disabled="!isSupervisor" @click="onImport">
            从钉钉素材报告导入
          </el-button>
          <el-button type="primary" :loading="importing" :disabled="!isSupervisor" @click="onRefreshFromDaily">
            刷新今日钉钉素材
          </el-button>
        </div>
      </div>
      <div v-if="!isSupervisor" class="role-hint">
        当前为客服专员角色，审核/导入操作仅主管/管理员可用（右上角可切换角色）。
      </div>
    </el-card>

    <!-- 列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe style="width: 100%" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="45" />
        <el-table-column label="商品" min-width="160">
          <template #default="{ row }">
            <div class="cell-product">{{ row.product_name }}</div>
            <div class="cell-sub">i_id: {{ row.i_id || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="SKU" width="130" prop="sku_code" />
        <el-table-column label="素材类型" width="130">
          <template #default="{ row }">
            {{ ASSET_TYPE_LABELS[row.asset_type] || row.asset_type }}
          </template>
        </el-table-column>
        <el-table-column label="素材标题" min-width="180" prop="asset_title" show-overflow-tooltip />
        <el-table-column label="素材链接" min-width="200">
          <template #default="{ row }">
            <el-link type="primary" :href="row.asset_url" target="_blank" :underline="false" class="link-text">
              {{ row.asset_url }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="(STATUS_TAG_TYPES[row.status] as any) || 'info'" size="small">
              {{ STATUS_LABELS[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可推荐" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.usable_for_agent ? 'success' : 'info'" size="small">
              {{ row.usable_for_agent ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90" prop="source" />
        <el-table-column label="更新时间" width="150">
          <template #default="{ row }">
            {{ row.updated_at ? row.updated_at.replace('T', ' ').slice(0, 16) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="copyUrl(row.asset_url)">复制链接</el-button>
            <el-button size="small" type="success" :disabled="!isSupervisor || row.status === 'approved'" @click="onApprove(row)">
              通过
            </el-button>
            <el-button size="small" type="danger" :disabled="!isSupervisor || row.status === 'rejected'" @click="onReject(row)">
              拒绝
            </el-button>
            <el-button size="small" :disabled="!isSupervisor" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager"
        background
        layout="total, sizes, prev, pager, next"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        @current-change="(p: number) => { page = p; fetchList() }"
        @size-change="(s: number) => { pageSize = s; page = 1; fetchList() }"
      />
    </el-card>

    <!-- 批量修改标签弹窗 -->
    <el-dialog v-model="batchDialogVisible" :title="(batchMode === 'add' ? '批量添加' : '批量移除') + '场景标签'" width="420px" destroy-on-close>
      <p style="margin:0 0 12px;color:#606266">已选 {{ selectedMedia.length }} 条素材</p>
      <el-form label-position="top">
        <el-form-item label="标签">
          <el-select v-model="batchTag" filterable allow-create default-first-option placeholder="选择或输入标签" style="width:100%">
            <el-option v-for="tag in SCENE_TAG_OPTIONS" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="batchDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="applyBatchTag">{{ batchMode === 'add' ? '添加' : '移除' }}</el-button>
      </template>
    </el-dialog>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" title="编辑素材" width="560px">
      <el-form :model="editing" label-width="90px">
        <el-form-item label="素材标题">
          <el-input v-model="editing.asset_title" />
        </el-form-item>
        <el-form-item label="素材类型">
          <el-select v-model="editing.asset_type" style="width: 100%">
            <el-option v-for="(label, key) in ASSET_TYPE_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="素材链接">
          <el-input v-model="editing.asset_url" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editing.status" style="width: 100%">
            <el-option v-for="(label, key) in STATUS_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="可推荐">
          <el-switch v-model="editing.usable_for_agent" />
          <span class="form-hint">开启后，AI 才会向客服推荐此素材</span>
        </el-form-item>
        <el-form-item label="场景标签">
          <el-input v-model="editingSceneTags" type="textarea" :rows="2" placeholder="用逗号分隔，例如：安装，尺寸，配件" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.media-library {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.stat-row {
  margin-bottom: 0;
}
.stat-card {
  text-align: center;
  padding: 6px 0;
}
.stat-num {
  font-size: 26px;
  font-weight: 700;
  color: #303133;
}
.stat-num.warn {
  color: #e6a23c;
}
.stat-num.ok {
  color: #67c23a;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.toolbar-right {
  margin-left: auto;
}
.role-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
.table-card {
  overflow: visible;
}
.cell-product {
  font-weight: 500;
}
.cell-sub {
  font-size: 12px;
  color: #909399;
}
.link-text {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}
.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
