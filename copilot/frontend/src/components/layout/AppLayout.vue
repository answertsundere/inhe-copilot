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
} from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()

const roleOptions = [
  { value: 'operator', label: '客服专员' },
  { value: 'supervisor', label: '主管' },
  { value: 'admin', label: '管理员' },
]

const currentRole = ref(localStorage.getItem('kb_user_role') || 'supervisor')

function onRoleChange(val: string) {
  currentRole.value = val
  localStorage.setItem('kb_user_role', val)
}

const pageTitle = computed(() => {
  return (route.meta?.title as string) || '资料管理'
})

const activeMenu = computed(() => route.path)

const menuItems = [
  { index: '/', icon: DataAnalysis, label: '总览' },
  { index: '/products', icon: Goods, label: '商品资料' },
  { index: '/shop-rules', icon: Notebook, label: '活动规则中心' },
  { index: '/qa', icon: ChatDotRound, label: '问答资料' },
  { index: '/reviews', icon: Checked, label: '审核中心' },
  { index: '/ai-updates', icon: DataAnalysis, label: 'AI 更新中心' },
  { index: '/sop', icon: Warning, label: '售后处理' },
  { index: '/cases', icon: Document, label: '案例库' },
  { index: '/traces', icon: Connection, label: '测试记录' },
  { index: '/health', icon: CircleCheck, label: '资料检查' },
]

const bottomMenuItems = [
  { index: '/guide', icon: QuestionFilled, label: '使用说明' },
]

function handleMenuSelect(index: string) {
  router.push(index)
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
          background-color="#1d1e2c"
          text-color="#bfcbd9"
          active-text-color="#409eff"
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
          background-color="#1d1e2c"
          text-color="#bfcbd9"
          active-text-color="#409eff"
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
  background-color: #1d1e2c;
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
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.logo-text {
  color: #ffffff;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 2px;
  text-decoration: none;
  cursor: pointer;
}

.logo-text:hover {
  opacity: 0.85;
}

.sidebar .el-menu {
  border-right: none;
}

.sidebar-menu-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.sidebar-menu-wrap > .el-menu:first-child {
  flex: 1;
  overflow-y: auto;
}

.bottom-menu {
  flex-shrink: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.main-container {
  background: #f5f7fa;
}

.top-header {
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  z-index: 10;
}

.page-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.header-right {
  display: flex;
  align-items: center;
}

.role-label {
  font-size: 13px;
  color: #606266;
  margin-right: 4px;
}

.main-content {
  padding: 20px;
  overflow-y: auto;
}
</style>
