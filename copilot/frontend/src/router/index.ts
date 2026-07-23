import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '../components/layout/AppLayout.vue'
import WorkbenchLayout from '../components/layout/WorkbenchLayout.vue'

const router = createRouter({
  history: createWebHistory('/ask/'),
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
          path: 'media-observation-review',
          name: 'media-observation-review',
          component: () => import('../views/ProductMediaObservationReviewPage.vue'),
          meta: { title: 'AI 视觉观察审核', hidden: true },
        },
        {
          path: 'service-rules',
          name: 'service-rules',
          component: () => import('../views/ServiceRulesPage.vue'),
          meta: { title: '服务规则' },
        },
        {
          path: 'shop-rules',
          name: 'shop-rules',
          component: () => import('../views/ShopRulesPage.vue'),
          meta: { title: '活动规则中心', hidden: true },
        },
        {
          path: 'qa',
          name: 'qa',
          component: () => import('../views/QAKnowledgePage.vue'),
          meta: { title: '问答资料', hidden: true },
        },
        {
          path: 'reviews',
          name: 'reviews',
          component: () => import('../views/ReviewCenterPage.vue'),
          meta: { title: '审核中心', hidden: true },
        },
        {
          path: 'ai-updates',
          name: 'ai-updates',
          component: () => import('../views/AIUpdateCenterPage.vue'),
          meta: { title: 'AI 更新' },
        },
        {
          path: 'sop',
          name: 'sop',
          component: () => import('../views/RiskSOPPage.vue'),
          meta: { title: '售后处理', hidden: true },
        },
        {
          path: 'cases',
          name: 'cases',
          component: () => import('../views/CaseLibraryPage.vue'),
          meta: { title: '案例库', hidden: true },
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
          meta: { title: '资料整理', hidden: true },
        },
        {
          path: 'health',
          name: 'health',
          component: () => import('../views/DataHealthPage.vue'),
          meta: { title: '资料检查', hidden: true },
        },
        {
          path: 'media',
          name: 'media',
          component: () => import('../views/MediaLibraryPage.vue'),
          meta: { title: '素材库', hidden: true },
        },
        {
          path: 'guide',
          name: 'guide',
          component: () => import('../views/UsageGuidePage.vue'),
          meta: { title: '使用说明' },
        },
        {
          path: 'real-accuracy-labels',
          name: 'real-accuracy-labels',
          component: () => import('../views/RealAccuracyLabelWorkbenchPage.vue'),
          meta: { title: '准确率人工标注', hidden: true },
        },
        {
          path: 'high-quality-conversation-review',
          name: 'high-quality-conversation-review',
          component: () => import('../views/HighQualityConversationReviewPage.vue'),
          meta: { title: '高质量长对话审核', hidden: true },
        },
      ],
    },
    {
      path: '/quality-replay',
      component: WorkbenchLayout,
      children: [
        {
          path: '',
          name: 'quality-replay',
          component: () => import('../views/RealConversationReplayPage.vue'),
          meta: { title: '真实回放质检' },
        },
      ],
    },
    {
      path: '/training-samples',
      name: 'training-samples',
      component: () => import('../views/TrainingSamplePage.vue'),
      meta: { title: '训练样本收集' },
    },
  ],
})

export default router
