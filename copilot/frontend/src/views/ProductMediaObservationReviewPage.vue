<script setup lang="ts">
import ProductMediaObservationPanel from '../components/product/ProductMediaObservationPanel.vue'
</script>

<template>
  <main class="review-page">
    <h1>AI 视觉观察审核</h1>
    <p>仅展示待审核候选。请核对来源图片后再采用，采用结果仍只保留在 Shadow 层。</p>
    <ProductMediaObservationPanel queue-mode />
  </main>
</template>

<style scoped lang="scss">
.review-page { padding: 20px; }
h1 { margin: 0 0 6px; font-size: 20px; }
p { margin: 0 0 16px; color: var(--kb-text-secondary); }
</style>
