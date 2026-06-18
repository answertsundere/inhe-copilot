<script setup lang="ts">
import ProductKnowledgeCard from './ProductKnowledgeCard.vue'
import type { ProductItem } from '../../utils/productStatus'

defineProps<{
  products: ProductItem[]
  loading?: boolean
}>()

const emit = defineEmits<{
  click: [id: number]
  fill: [id: number]
  review: [id: number]
  retest: [id: number]
}>()
</script>

<template>
  <div v-loading="loading" class="card-grid">
    <ProductKnowledgeCard
      v-for="product in products"
      :key="product.id"
      :product="product"
      @click="emit('click', $event)"
      @fill="emit('fill', $event)"
      @review="emit('review', $event)"
      @retest="emit('retest', $event)"
    />
    <div v-if="!loading && !products.length" class="empty-wrap">
      <el-empty description="暂无商品数据" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.empty-wrap {
  grid-column: 1 / -1;
  padding: 40px 0;
}

@media (max-width: 1366px) {
  .card-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (min-width: 1920px) {
  .card-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}
</style>
