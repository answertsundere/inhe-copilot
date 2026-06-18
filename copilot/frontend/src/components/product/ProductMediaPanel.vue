<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getMediaAssets,
  updateMedia,
  deleteMedia,
  uploadMediaAsset,
  batchUpdateMediaTags,
  ASSET_TYPE_LABELS,
  STATUS_LABELS,
  STATUS_TAG_TYPES,
  RISK_LEVEL_OPTIONS,
  SOURCE_TYPE_OPTIONS,
  MEDIA_PURPOSE_OPTIONS,
  APPLICABLE_STYLE_TYPE_OPTIONS,
  ANSWER_SCENARIO_OPTIONS,
  AUTO_SEND_LEVEL_OPTIONS,
  getMediaPurpose,
  getApplicableStyle,
  getAnswerScenarios,
  getAutoSendLevel,
  buildMediaUpdatePayload,
  type MediaAsset,
} from '../../api/media'
import { useCurrentUser } from '../../composables/useCurrentUser'

const props = defineProps<{
  product: any
}>()

const emit = defineEmits<{
  refreshed: []
}>()

const { canEdit } = useCurrentUser()
const loading = ref(false)
const assets = ref<MediaAsset[]>([])
const previewList = computed(() => assets.value.map((a) => a.asset_url).filter(Boolean))

const mediaPurposeOrder = [
  'appearance_image', 'size_image', 'install_image', 'install_video',
  'packing_list_image', 'accessory_image', 'certificate_image', 'material_image', 'aftersales_image', 'other',
]

const groupedAssets = computed(() => {
  const groups: Record<string, MediaAsset[]> = {}
  assets.value.forEach((asset) => {
    const purpose = getMediaPurpose(asset)
    if (!groups[purpose]) groups[purpose] = []
    groups[purpose].push(asset)
  })
  return Object.entries(groups).sort((a, b) => {
    const ia = mediaPurposeOrder.indexOf(a[0])
    const ib = mediaPurposeOrder.indexOf(b[0])
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })
})

function ensureSourceRaw(asset: MediaAsset) {
  if (!asset.source_raw || typeof asset.source_raw !== 'object') asset.source_raw = {}
  return asset.source_raw
}

function normalizeAsset(asset: MediaAsset) {
  const sr = ensureSourceRaw(asset)
  sr.media_purpose = getMediaPurpose(asset)
  const style = getApplicableStyle(asset)
  sr.applicable_style = {
    scope_type: style.scope_type || 'all',
    scope_values: style.scope_values || [],
    scope_note: style.scope_note || '',
  }
  sr.answer_scenarios = getAnswerScenarios(asset)
  sr.auto_send_level = getAutoSendLevel(asset)
  sr.risk_level = sr.risk_level || 'low'
  sr.source_type = sr.source_type || asset.source || 'manual'
}

async function fetchAssets() {
  if (!props.product) return
  loading.value = true
  try {
    const params: Record<string, any> = { limit: 200 }
    if (props.product.id) params.product_id = props.product.id
    if (props.product.i_id) params.i_id = props.product.i_id
    if (props.product.product_name) params.product_name = props.product.product_name
    const { data } = await getMediaAssets(params)
    assets.value = (data.items || []).map((a: MediaAsset) => {
      normalizeAsset(a)
      return a
    })
  } catch {
    ElMessage.warning('加载商品素材失败')
    assets.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchAssets)

function isVideo(asset: MediaAsset) {
  return String(asset.asset_type || '').includes('video') || /\.(mp4|webm|mov)(\?.*)?$/i.test(asset.asset_url || '')
}

function isImage(asset: MediaAsset) {
  return /\.(png|jpg|jpeg|webp|gif)(\?.*)?$/i.test(asset.asset_url || '')
}

function isExpired(asset: MediaAsset) {
  if (asset.refresh_status === 'needs_refresh') return true
  const url = asset.asset_url || ''
  const m = url.match(/[?&]Expires=(\d+)/)
  if (m) {
    const ts = parseInt(m[1], 10)
    if (!isNaN(ts)) return Date.now() > ts * 1000
  }
  return false
}

async function saveAsset(asset: MediaAsset) {
  try {
    const { data } = await updateMedia(asset.id, buildMediaUpdatePayload(asset))
    ElMessage.success('素材已保存')
    const saved = data.asset as MediaAsset
    normalizeAsset(saved)
    const idx = assets.value.findIndex((a) => a.id === saved.id)
    if (idx >= 0) assets.value[idx] = saved
    emit('refreshed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存素材失败')
  }
}

async function removeAsset(asset: MediaAsset) {
  try {
    await ElMessageBox.confirm('删除后素材将从素材库移除，是否继续？', '删除素材', { type: 'warning' })
    await deleteMedia(asset.id)
    ElMessage.success('素材已删除')
    await fetchAssets()
    emit('refreshed')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '删除失败')
  }
}

async function approveAsset(asset: MediaAsset) {
  asset.status = 'approved'
  asset.usable_for_agent = true
  await saveAsset(asset)
}

async function markUnavailable(asset: MediaAsset) {
  asset.usable_for_agent = false
  asset.status = 'rejected'
  await saveAsset(asset)
}

async function handleUpload(options: any) {
  const file = options.file
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  const isVideoFile = ['mp4', 'webm', 'mov'].includes(ext)
  const assetType = isVideoFile ? 'install_video' : 'sku_image'

  const formData = new FormData()
  formData.append('file', file)
  formData.append('product_id', String(props.product.id))
  if (props.product.i_id) formData.append('i_id', props.product.i_id)
  if (props.product.product_name) formData.append('product_name', props.product.product_name)
  formData.append('asset_type', assetType)
  formData.append('asset_title', file.name)
  formData.append('scene_tags', JSON.stringify([]))

  try {
    const { data } = await uploadMediaAsset(formData)
    ElMessage.success('素材上传成功')
    const uploaded = data.asset as MediaAsset
    normalizeAsset(uploaded)
    assets.value.push(uploaded)
    emit('refreshed')
    if (options.onSuccess) options.onSuccess()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '上传失败')
    if (options.onError) options.onError(e)
  }
}

function getLinkStatus(asset: MediaAsset) {
  if (isExpired(asset)) return { label: '已过期', type: 'danger' }
  const url = asset.asset_url || ''
  const m = url.match(/[?&]Expires=(\d+)/)
  if (m) {
    const ts = parseInt(m[1], 10) * 1000
    const days = (ts - Date.now()) / 86400000
    if (days < 7) return { label: '即将过期', type: 'warning' }
  }
  if (asset.refresh_status === 'needs_refresh') return { label: '待刷新', type: 'warning' }
  return { label: '有效', type: 'success' }
}

function copyLink(url: string) {
  navigator.clipboard.writeText(url).then(() => ElMessage.success('链接已复制')).catch(() => ElMessage.error('复制失败'))
}

function addAnswerScenario(asset: MediaAsset, scenario: string) {
  const sr = ensureSourceRaw(asset)
  const scenarios = new Set((sr.answer_scenarios || []) as string[])
  scenarios.add(scenario)
  sr.answer_scenarios = Array.from(scenarios)
}
</script>

<template>
  <div v-loading="loading" class="media-panel">
    <div class="media-toolbar">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="商品素材管理"
        description="素材统一归到商品详情维护。只有已审核且可推荐的素材，Agent 才会自动放进回复计划。"
        style="flex: 1; min-width: 260px"
      />
      <div class="toolbar-actions">
        <el-upload :show-file-list="false" :http-request="handleUpload" :disabled="!canEdit" accept="image/*,video/*" style="display: inline-block">
          <el-button type="primary" :disabled="!canEdit">上传图片/视频</el-button>
        </el-upload>
        <el-button :disabled="!assets.length" @click="batchUpdateMediaTags(assets.map(a => a.id), [], [])">
          批量标签
        </el-button>
      </div>
    </div>

    <div v-if="!canEdit" class="permission-hint">
      <el-alert type="warning" :closable="false" show-icon title="当前为客服角色" description="素材的保存、审核、删除操作需要主管权限。" />
    </div>

    <div v-if="groupedAssets.length" class="media-groups">
      <div v-for="[type, list] in groupedAssets" :key="type" class="media-group">
        <div class="group-title">
          <span>{{ MEDIA_PURPOSE_OPTIONS.find((o) => o.value === type)?.label || type }}</span>
          <el-tag size="small" type="info">{{ list.length }}</el-tag>
        </div>
        <div class="media-cards">
          <div v-for="asset in list" :key="asset.id" class="media-card">
            <div class="media-preview">
              <div v-if="isExpired(asset)" class="expired-overlay">链接已过期</div>
              <el-image
                v-else-if="isImage(asset)"
                :src="asset.asset_url"
                :preview-src-list="previewList"
                :initial-index="assets.findIndex(a => a.id === asset.id)"
                fit="cover"
                class="preview-image"
                hide-on-click-modal
                preview-teleported
              />
              <video v-else-if="isVideo(asset)" :src="asset.asset_url" class="preview-video" controls />
              <div v-else class="unknown-file">{{ ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type }}</div>
            </div>

            <div class="media-fields">
              <el-input v-model="asset.asset_title" :disabled="!canEdit" size="small" placeholder="标题" />
              <el-select v-model="ensureSourceRaw(asset).media_purpose" :disabled="!canEdit" size="small" placeholder="素材用途">
                <el-option v-for="opt in MEDIA_PURPOSE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <el-select
                v-model="ensureSourceRaw(asset).applicable_style.scope_type"
                :disabled="!canEdit"
                size="small"
                placeholder="适用范围"
              >
                <el-option v-for="opt in APPLICABLE_STYLE_TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <el-select
                v-if="ensureSourceRaw(asset).applicable_style.scope_type !== 'all'"
                v-model="ensureSourceRaw(asset).applicable_style.scope_values"
                :disabled="!canEdit"
                size="small"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="适用 SKU / 颜色 / 规格"
              />
              <el-select
                v-model="ensureSourceRaw(asset).answer_scenarios"
                :disabled="!canEdit"
                size="small"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="可回答标签"
              >
                <el-option v-for="opt in ANSWER_SCENARIO_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <div class="quick-tags">
                <el-button
                  v-for="opt in ANSWER_SCENARIO_OPTIONS.slice(0, 6)"
                  :key="opt.value"
                  size="small"
                  text
                  :disabled="!canEdit"
                  @click="addAnswerScenario(asset, opt.value)"
                >
                  +{{ opt.label }}
                </el-button>
              </div>
              <div class="field-row">
                <el-select v-model="ensureSourceRaw(asset).risk_level" :disabled="!canEdit" size="small" placeholder="风险">
                  <el-option v-for="opt in RISK_LEVEL_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
                <el-select v-model="ensureSourceRaw(asset).source_type" :disabled="!canEdit" size="small" placeholder="来源">
                  <el-option v-for="opt in SOURCE_TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
              </div>
              <div class="field-row">
                <el-select v-model="asset.status" :disabled="!canEdit" size="small" placeholder="审核状态">
                  <el-option v-for="(label, key) in STATUS_LABELS" :key="key" :label="label" :value="key" />
                </el-select>
                <div class="usable-switch">
                  <span>可推荐</span>
                  <el-switch v-model="asset.usable_for_agent" :disabled="!canEdit" />
                </div>
              </div>
            </div>

            <div class="media-meta">
              <div class="meta-row">
                <el-tag size="small" :type="(STATUS_TAG_TYPES[asset.status] as any) || 'info'">{{ STATUS_LABELS[asset.status] || asset.status }}</el-tag>
                <el-tag size="small" :type="getLinkStatus(asset).type as any">{{ getLinkStatus(asset).label }}</el-tag>
              </div>
              <div class="meta-row secondary">
                <span>上传：{{ asset.created_by || '-' }}</span>
                <span>更新：{{ asset.updated_by || '-' }}</span>
              </div>
            </div>

            <div class="media-actions">
              <el-button size="small" type="primary" :disabled="!canEdit" @click="saveAsset(asset)">保存</el-button>
              <el-button size="small" :disabled="!canEdit" @click="approveAsset(asset)">审核通过</el-button>
              <el-button size="small" :disabled="!canEdit" @click="markUnavailable(asset)">标记不可用</el-button>
              <el-button size="small" text @click="copyLink(asset.asset_url)">复制链接</el-button>
              <el-button size="small" text type="danger" :disabled="!canEdit" @click="removeAsset(asset)">删除</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-empty v-else description="暂无商品素材。可以先上传，或从钉钉同步。" />
  </div>
</template>

<style scoped lang="scss">
.media-panel {
  padding: 4px;
}
.media-toolbar {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.toolbar-actions {
  display: flex;
  gap: 8px;
}
.permission-hint {
  margin-bottom: 12px;
}
.media-groups {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--kb-text-primary);
  margin-bottom: 10px;
}
.media-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.media-card {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border);
  border-radius: var(--kb-radius-lg);
  padding: 12px;
  box-shadow: var(--kb-shadow-card);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.media-preview {
  width: 100%;
  height: 140px;
  border-radius: var(--kb-radius-md);
  background: var(--kb-bg-hover);
  border: 1px solid var(--kb-border);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}
.preview-image,
.preview-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.expired-overlay {
  color: var(--kb-danger-text);
  font-weight: 600;
  background: var(--kb-danger-bg);
  padding: 6px 12px;
  border-radius: var(--kb-radius-md);
}
.unknown-file {
  font-size: 13px;
  color: var(--kb-text-secondary);
  text-align: center;
  padding: 0 12px;
}
.media-fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field-row {
  display: flex;
  gap: 8px;
}
.usable-switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--kb-text-secondary);
  white-space: nowrap;
}
.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
.media-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.meta-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.meta-row.secondary {
  font-size: 11px;
  color: var(--kb-text-secondary);
}
.media-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
}
</style>
