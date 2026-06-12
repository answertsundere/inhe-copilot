<script setup lang="ts">
import { ref, computed } from 'vue'

const props = withDefaults(
  defineProps<{
    text: string
    maxLines?: number
  }>(),
  { maxLines: 3 },
)

const expanded = ref(false)

const mayOverflow = computed(() => props.text.length > 200)

const lineHeight = computed(() => `${props.maxLines}`)
</script>

<template>
  <div class="collapsible-text">
    <div
      class="text-content"
      :class="{ 'is-clamped': !expanded && mayOverflow }"
      :style="{ '--max-lines': maxLines }"
    >
      {{ text }}
    </div>
    <el-button
      v-if="mayOverflow"
      link
      type="primary"
      size="small"
      class="toggle-btn"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起' : '展开' }}
    </el-button>
  </div>
</template>

<style scoped>
.collapsible-text {
  .text-content {
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.6;
  }

  .is-clamped {
    display: -webkit-box;
    -webkit-line-clamp: var(--max-lines);
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .toggle-btn {
    margin-top: 4px;
    padding: 0;
  }
}
</style>
