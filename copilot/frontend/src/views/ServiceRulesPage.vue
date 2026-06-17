<script setup lang="ts">
import { ref } from 'vue'
import QAKnowledgePage from './QAKnowledgePage.vue'
import RiskSOPPage from './RiskSOPPage.vue'
import ShopRulesPage from './ShopRulesPage.vue'
import LogisticsRulesPage from './LogisticsRulesPage.vue'
import HighRiskTalkPage from './HighRiskTalkPage.vue'

const activeTab = ref('qa')
</script>

<template>
  <div class="service-rules-page">
    <el-tabs v-model="activeTab" type="border-card" class="rule-tabs">
      <el-tab-pane label="通用问答" name="qa">
        <QAKnowledgePage />
      </el-tab-pane>
      <el-tab-pane label="售后流程" name="sop">
        <RiskSOPPage />
      </el-tab-pane>
      <el-tab-pane label="活动规则" name="activity">
        <ShopRulesPage />
      </el-tab-pane>
      <el-tab-pane label="物流规则" name="logistics">
        <LogisticsRulesPage />
      </el-tab-pane>
      <el-tab-pane label="高风险话术" name="high-risk">
        <HighRiskTalkPage />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.service-rules-page {
  padding: 16px;
}
.rule-tabs :deep(.el-tabs__content) {
  padding: 16px 0 0 0;
}
</style>
