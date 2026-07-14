import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// Track whether we're already handling a 401 to prevent loops
let handling401 = false

// Request interceptor – attach JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor – handle 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !handling401) {
      handling401 = true
      localStorage.removeItem('token')
      // Use location.href only if not already on login page
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login'
      }
      // Reset the flag after a delay (page will reload before this if redirecting)
      setTimeout(() => { handling401 = false }, 1000)
    }
    return Promise.reject(error)
  }
)

export default api
