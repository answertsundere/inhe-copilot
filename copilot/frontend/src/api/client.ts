import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/ask/api/kb',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截 - 附加用户信息
apiClient.interceptors.request.use((config) => {
  const role = localStorage.getItem('kb_user_role') || 'supervisor'
  const name = localStorage.getItem('kb_user_name') || 'admin'
  config.headers['X-User-Role'] = role
  config.headers['X-User-Name'] = name
  return config
})

// 响应拦截 - 统一错误处理
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const msg = error.response?.data?.error || error.message || '请求失败'
    console.error('[API Error]', msg)
    return Promise.reject(error)
  },
)

export default apiClient
