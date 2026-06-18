<script setup lang="ts">
import { computed } from 'vue'
import StatusTag from '../common/StatusTag.vue'
import RiskBadge from '../common/RiskBadge.vue'
import {
  getProductGrade,
  getGradeColor,
  getAgentStatusInfo,
  getGapTags,
  getCompletenessColor,
  type ProductItem,
} from '../../utils/productStatus'

const props = defineProps<{
  products: ProductItem[]
  loading?: boolean
}>()

const emit = defineEmits<{
  click: [id: number]
  selectionChange: [ids: number[]]
}>()

const tableData = computed(() => props.products)

function onRowClick(row: ProductItem) {
  emit('click', row.id)
}

function onSelectionChange(rows: ProductItem[]) {
  emit('selectionChange', rows.map((r) => r.id))
}

function renderAgentStatus(row: ProductItem) {
  const info = getAgentStatusInfo(row)
  return info.label
}
</script>

<template>
  <el-table
    :data="tableData"
    v-loading="loading"
    stripe
    size="small"
    @selection-change="onSelectionChange"
    @row-click="onRowClick"
  >
    <el-table-column type="selection" width="36" />
    <el-table-column label="商品" min-width="200">
      <template #default="{ row }">
        <a class="product-link" @click.stop="emit('click', row.id)">
          {{ row.specs?.display_name || row.product_name }}
        </a>
        <div class="sku-line">{{ row.i_id }}</div>
      </template>
    </el-table-column>
    <el-table-column label="类目" width="150">
      <template #default="{ row }">
        <div class="cat-text">{{ row.category_l1 }}</div>
        <div class="cat-sub">{{ row.category_l2 }}{{ row.category_l3 ? ' / ' + row.category_l3 : '' }}</div>
      </template>
    </el-table-column>
    <el-table-column label="等级" width="70" align="center">
      <template #default="{ row }">
        <span class="grade-text" :style="{ color: getGradeColor(getProductGrade(row)) }">
          {{ getProductGrade(row) }}
        </span>
      </template>
    </el-table-column>
    <el-table-column label="完整度" width="120">
      <template #default="{ row }">
        <el-progress
          :percentage="row.completeness_score || 0"
          :stroke-width="12"
          :color="getCompletenessColor(row.completeness_score || 0)"
          :format="(p: number) => p + '%'"
        />
      </template>
    </el-table-column>
    <el-table-column label="问答" width="80" align="center">
      <template #default="{ row }">
        <span :class="row.qa_count ? '' : 'text-muted'">{{ row.qa_count || 0 }}</span>
        <el-tag v-if="row.high_risk_qa_count" type="danger" size="small" style="margin-left: 4px">
          {{ row.high_risk_qa_count }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="Agent" width="110" align="center">
      <template #default="{ row }">
        <el-tooltip :content="getAgentStatusInfo(row).reason" placement="top">
          <el-tag :type="getAgentStatusInfo(row).type" size="small">
            {{ renderAgentStatus(row) }}
          </el-tag>
        </el-tooltip>
      </template>
    </el-table-column>
    <el-table-column label="健康标签" min-width="180">
      <template #default="{ row }">
        <el-tag
          v-for="tag in getGapTags(row).slice(0, 3)"
          :key="tag.text"
          size="small"
          :type="tag.type as any"
          style="margin: 1px 2px"
        >
          {{ tag.text }}
        </el-tag>
        <el-tag v-if="getGapTags(row).length > 3" size="small" type="info">+{{ getGapTags(row).length - 3 }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="状态" width="90">
      <template #default="{ row }">
        <StatusTag :status="row.status" />
      </template>
    </el-table-column>
    <el-table-column label="操作" width="80" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" size="small" @click.stop="emit('click', row.id)">详情</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped lang="scss">
.product-link {
  color: var(--kb-accent);
  cursor: pointer;
  font-weight: 500;
  font-size: 13px;
}
.product-link:hover {
  text-decoration: underline;
}
.sku-line {
  font-size: 11px;
  color: var(--kb-text-secondary);
}
.cat-text {
  font-size: 13px;
}
.cat-sub {
  font-size: 11px;
  color: var(--kb-text-secondary);
}
.text-muted {
  color: var(--kb-text-tertiary);
}
.grade-text {
  font-weight: 700;
  font-size: 14px;
}
</style>
