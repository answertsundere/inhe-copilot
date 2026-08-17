<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatDotRound,
  Checked,
  Collection,
  DataAnalysis,
  House,
  Search,
  Setting,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const activeMenu = computed(() => route.path)
const pageTitle = computed(() => String(route.meta.title || '智能客服工作台'))
const pageDescription = computed(() => String(route.meta.description || ''))

const menuItems = [
  { index: '/real-test', icon: ChatDotRound, label: '智能回复体验台' },
  { index: '/quality-replay', icon: Checked, label: '质检测评' },
  { index: '/knowledge-search', icon: Search, label: '知识检索', disabled: true },
  { index: '/reports', icon: DataAnalysis, label: '报表分析', disabled: true },
  { index: '/settings', icon: Setting, label: '系统设置', disabled: true },
]

function handleMenuSelect(index: string) {
  const item = menuItems.find((entry) => entry.index === index)
  if (!item || item.disabled) return
  router.push(index)
}

function openWorkbench() {
  window.location.href = '/ask/real-test'
}
</script>

<template>
  <el-container class="workbench-layout">
    <el-header class="workbench-top" height="38px">
      <div class="top-left">
        <a href="/ask/real-test" class="brand">
          <span class="brand-mark">IN</span>
          <span>INHE 智能客服助手</span>
        </a>
        <nav class="top-nav">
          <a href="/ask/real-test">工作台</a>
          <a href="/ask/training-samples" target="_blank">训练样本收集</a>
          <a href="/ask/" class="kb-link">
            <el-icon><Collection /></el-icon>
            知识库后台
          </a>
        </nav>
      </div>
      <el-button size="small" :icon="House" @click="openWorkbench">返回工作台</el-button>
    </el-header>

    <el-container class="workbench-body">
      <el-aside width="218px" class="workbench-sidebar">
        <el-menu
          :default-active="activeMenu"
          class="side-menu"
          @select="handleMenuSelect"
        >
          <el-menu-item
            v-for="item in menuItems"
            :key="item.index"
            :index="item.index"
            :disabled="item.disabled"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-main class="workbench-main">
        <div class="page-heading">
          <div>
            <h1>{{ pageTitle }}</h1>
            <p v-if="pageDescription">{{ pageDescription }}</p>
          </div>
        </div>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.workbench-layout {
  min-height: 100vh;
  background: #f3f6fb;
  color: #111827;
}

.workbench-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  background: #ffffff;
  border-bottom: 1px solid #dbe2ea;
}

.top-left {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #111827;
  font-size: 16px;
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 24px;
  border-radius: 5px;
  background: #2563eb;
  color: #ffffff;
  font-size: 13px;
  font-weight: 800;
}

.top-nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.top-nav a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 12px;
  border-radius: 6px;
  color: #1f2937;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
}

.top-nav a:hover,
.top-nav .kb-link:hover {
  background: #eef4ff;
  color: #1d4ed8;
}

.workbench-body {
  height: calc(100vh - 38px);
}

.workbench-sidebar {
  background: #ffffff;
  border-right: 1px solid #dbe2ea;
  overflow: hidden;
}

.side-menu {
  padding: 14px 10px;
  border-right: 0;
  background: transparent;
}

.side-menu :deep(.el-menu-item) {
  height: 36px;
  margin-bottom: 6px;
  border-radius: 6px;
  color: #334155;
  font-size: 14px;
  font-weight: 600;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: #eaf1ff;
  color: #2563eb;
}

.side-menu :deep(.el-menu-item.is-disabled) {
  color: #64748b;
  opacity: 1;
  cursor: default;
}

.workbench-main {
  min-width: 0;
  padding: 16px;
  overflow: auto;
}

@media (max-width: 860px) {
  .workbench-top {
    padding: 0 10px;
  }

  .top-nav,
  .workbench-top > .el-button,
  .workbench-sidebar {
    display: none;
  }

  .workbench-main {
    padding: 10px;
  }

  .page-heading h1 {
    font-size: 18px;
  }
}

.page-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.page-heading h1 {
  margin: 0 0 4px;
  font-size: 20px;
  line-height: 1.35;
}

.page-heading p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
</style>
