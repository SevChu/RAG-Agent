import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/training',
      component: () => import('@/views/training/TrainingLayout.vue'),
      children: [
        { path: '', redirect: '/training/datasets' },
        { path: 'datasets', component: () => import('@/views/training/TrainingDatasets.vue') },
        { path: 'new', component: () => import('@/views/training/TrainingWizard.vue') },
        { path: 'runs', component: () => import('@/views/training/TrainingRuns.vue') },
        { path: 'runs/:runId', component: () => import('@/views/training/TrainingRunDetail.vue') },
        { path: 'adapters', component: () => import('@/views/training/TrainingAdapters.vue') },
        {
          path: 'adapters/:adapterId',
          component: () => import('@/views/training/TrainingAdapterDetail.vue'),
        },
      ],
    },
    {
      path: '/',
      redirect: '/courses',
    },
    {
      path: '/courses',
      name: 'courses',
      component: () => import('@/views/CourseSpaceView.vue'),
    },
    {
      path: '/courses/:courseId',
      name: 'course-detail',
      component: () => import('@/views/CourseDetailView.vue'),
    },
    {
      path: '/chat/:conversationId?',
      name: 'quick-chat',
      component: () => import('@/views/QuickChatView.vue'),
    },
    {
      path: '/assistant/:conversationId?',
      name: 'study-assistant',
      component: () => import('@/views/StudyAssistantView.vue'),
    },
    {
      path: '/agents',
      name: 'agent-profiles',
      component: () => import('@/views/AgentProfilesView.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
    },
  ],
})

export default router
