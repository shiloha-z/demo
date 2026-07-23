import axios from 'axios'
import { MessagePlugin } from 'tdesign-vue-next'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

let handling401 = false
// Avoid duplicate toasts for the same error within a short window
const _recentErrors = new Map<string, number>()

function _shouldNotify(key: string): boolean {
  const now = Date.now()
  const last = _recentErrors.get(key) || 0
  if (now - last < 2000) return false
  _recentErrors.set(key, now)
  for (const [k, t] of _recentErrors) {
    if (now - t > 10000) _recentErrors.delete(k)
  }
  return true
}

// Request interceptor – attach JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type']
  }
  return config
})

// Response interceptor – unified error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || ''
    const url = error.config?.url || ''

    if (status === 401 && !handling401) {
      handling401 = true
      localStorage.removeItem('token')
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login'
      }
      setTimeout(() => { handling401 = false }, 1000)
      return Promise.reject(error)
    }

    // Show a unified toast for common errors — components can still
    // catch and override with a custom fallback message if needed.
    if (status && _shouldNotify(`${status}:${url}`)) {
      switch (status) {
        case 403:
          MessagePlugin.warning(detail || '权限不足，无法执行此操作')
          break
        case 404:
          MessagePlugin.warning(detail || '请求的资源不存在')
          break
        case 409:
          // Let individual components handle 409 with their own UI
          // (e.g. confirm dialogs for duplicate-project-name warnings).
          break
        case 422: {
          // FastAPI 422 detail is an array of field errors; extract a readable message.
          let msg = '提交的数据格式不正确'
          if (typeof detail === 'string' && detail) {
            msg = detail
          } else if (Array.isArray(detail) && detail.length > 0) {
            const first = detail[0]
            const loc = (first?.loc || []).filter((s: string) => s !== 'body').join('.')
            msg = loc ? `${loc}: ${first.msg}` : first.msg
          }
          MessagePlugin.warning(msg)
          break
        }
        case 500:
        case 502:
        case 503:
          MessagePlugin.error(detail || '服务暂时不可用，请稍后重试')
          break
      }
    }

    return Promise.reject(error)
  },
)

/**
 * Extract a user-facing message from an Axios error.
 * Use in catch blocks: MessagePlugin.error(getErrorMessage(e, '默认错误信息'))
 */
export function getErrorMessage(e: any, fallback = '操作失败'): string {
  return e?.response?.data?.detail || e?.message || fallback
}

export default api
