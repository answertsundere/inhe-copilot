import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '../components/layout/AppLayout.vue'

const router = createRouter({
  history: createWebHistory('/ask/kb-admin/'),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('../views/KnowledgeDashboardPage.vue'),
          meta: { title: '总览' },
        },
        {
          path: 'products',
          name: 'products',
          component: () => import('../views/ProductKnowledgePage.vue'),
          meta: { title: '商品资料' },
        },
        {
          path: 'shop-rules',
          name: 'shop-rules',
          component: () => import('../views/ShopRulesPage.vue'),
          meta: { title: '活动规则中心' },
        },
        {
          path: 'qa',
          name: 'qa',
          component: () => import('../views/QAKnowledgePage.vue'),
          meta: { title: '问答资料' },
        },
        {
          path: 'reviews',
          name: 'reviews',
          component: () => import('../views/ReviewCenterPage.vue'),
          meta: { title: '审核中心' },
        },
        {
          path: 'ai-updates',
          name: 'ai-updates',
          component: () => import('../views/AIUpdateCenterPage.vue'),
          meta: { title: 'AI 更新中心' },
        },
        {
          path: 'sop',
          name: 'sop',
          component: () => import('../views/RiskSOPPage.vue'),
          meta: { title: '售后处理' },
        },
        {
          path: 'cases',
          name: 'cases',
          component: () => import('../views/CaseLibraryPage.vue'),
          meta: { title: '案例库' },
        },
        {
          path: 'traces',
          name: 'traces',
          component: () => import('../views/AgentTracePage.vue'),
          meta: { title: '测试记录' },
        },
        {
          path: 'rag',
          name: 'rag',
          component: () => import('../views/RAGKnowledgePage.vue'),
          meta: { title: '资料整理' },
        },
        {
          path: 'health',
          name: 'health',
          component: () => import('../views/DataHealthPage.vue'),
          meta: { title: '资料检查' },
        },
        {
          path: 'guide',
          name: 'guide',
          component: () => import('../views/UsageGuidePage.vue'),
          meta: { title: '使用说明' },
        },
      ],
    },
  ],
})

export default router
