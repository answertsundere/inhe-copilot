<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  DataAnalysis,
  Goods,
  ChatDotRound,
  Checked,
  Warning,
  Document,
  Connection,
  CircleCheck,
  Notebook,
  QuestionFilled,
  Picture,
  Back,
  Collection,
} from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()

const roleOptions = [
  { value: 'operator', label: '客服专员' },
  { value: 'supervisor', label: '主管' },
  { value: 'admin', label: '管理员' },
]

const currentRole = ref(localStorage.getItem('kb_user_role') || 'operator')

function onRoleChange(val: string) {
  currentRole.value = val
  localStorage.setItem('kb_user_role', val)
}

const pageTitle = computed(() => {
  return (route.meta?.title as string) || '资料管理'
})

const activeMenu = computed(() => route.path)

const menuItems = [
  { index: '/real-test', icon: Checked, label: '真实回放质检' },
  { index: '/', icon: DataAnalysis, label: '总览' },
  { index: '/products', icon: Goods, label: '商品资料' },
  { index: '/service-rules', icon: Notebook, label: '服务规则' },
  { index: '/training-samples', icon: Collection, label: '训练样本收集' },
  { index: '/ai-updates', icon: DataAnalysis, label: 'AI 更新中心' },
  { index: '/traces', icon: Connection, label: '测试记录' },
]

const bottomMenuItems = [
  { index: '/guide', icon: QuestionFilled, label: '使用说明' },
]

function handleMenuSelect(index: string) {
  router.push(index)
}

function openWorkbench() {
  window.location.href = '/ask/real-test'
}

function openTrainingSamples() {
  router.push('/training-samples')
}
</script>

<template>
  <el-container class="app-layout">
    <el-aside width="220px" class="sidebar">
      <div class="sidebar-header">
        <a href="/ask/" class="logo-text">INHE 资料库</a>
      </div>
      <div class="sidebar-menu-wrap">
        <el-menu
          :default-active="activeMenu"
          :unique-opened="true"
          router
          @select="handleMenuSelect"
        >
          <el-menu-item v-for="item in menuItems" :key="item.index" :index="item.index">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>

        <el-menu
          class="bottom-menu"
          :default-active="activeMenu"
          :unique-opened="true"
          router
          @select="handleMenuSelect"
        >
          <el-menu-item v-for="item in bottomMenuItems" :key="item.index" :index="item.index">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>
      </div>
    </el-aside>

    <el-container class="main-container">
      <el-header class="top-header" height="56px">
        <h3 class="page-title">{{ pageTitle }}</h3>
        <div class="header-right">
          <el-button class="workbench-button" size="small" :icon="Back" @click="openWorkbench">
            返回工作台
          </el-button>
          <el-button type="primary" size="small" :icon="Collection" @click="openTrainingSamples">
            提交训练样本
          </el-button>
          <span class="role-label">角色：</span>
          <el-select v-model="currentRole" size="small" style="width: 130px" @change="onRoleChange">
            <el-option
              v-for="opt in roleOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </div>
      </el-header>

      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-layout {
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  background-color: var(--kb-bg-sidebar);
  overflow: hidden;
  border-right: none;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid var(--kb-border-sidebar);
  flex-shrink: 0;
}

.logo-text {
  color: #ffffff;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 1px;
  text-decoration: none;
  cursor: pointer;
}

.logo-text:hover {
  opacity: 0.85;
}

.sidebar :deep(.el-menu) {
  border-right: none;
  background-color: transparent;
}

.sidebar :deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  margin: 4px 10px;
  padding: 0 12px !important;
  border-radius: var(--kb-radius-md);
  color: rgba(255, 255, 255, 0.65);
  font-size: 14px;
  font-weight: 500;
}

.sidebar :deep(.el-menu-item .el-icon) {
  margin-right: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.sidebar :deep(.el-menu-item:hover) {
  background-color: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.9);
}

.sidebar :deep(.el-menu-item:hover .el-icon) {
  color: rgba(255, 255, 255, 0.75);
}

.sidebar :deep(.el-menu-item.is-active) {
  background-color: rgba(79, 106, 246, 0.15);
  color: #7b8ffc;
}

.sidebar :deep(.el-menu-item.is-active .el-icon) {
  color: #7b8ffc;
}

.sidebar-menu-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding-top: 8px;
}

.sidebar-menu-wrap > .el-menu:first-child {
  flex: 1;
  overflow-y: auto;
}

.bottom-menu {
  flex-shrink: 0;
  border-top: 1px solid var(--kb-border-sidebar);
  padding-top: 8px;
  padding-bottom: 8px;
}

.main-container {
  background: var(--kb-bg-page);
}

.top-header {
  background: var(--kb-bg-card);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--kb-border);
  z-index: 10;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--kb-text-primary);
  line-height: 1.4;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.workbench-button {
  font-weight: 500;
}

.role-label {
  font-size: 13px;
  color: var(--kb-text-secondary);
}

.main-content {
  padding: 24px;
  overflow-y: auto;
}
</style>
