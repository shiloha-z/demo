import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    target: 'es2020',
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Monaco Editor — ~1.5 MB, loaded only in FileManager + DiffReviewer
          if (id.includes('monaco-editor')) return 'monaco'
          // TDesign Vue Next component library
          if (id.includes('tdesign-vue-next')) return 'tdesign'
          // Markdown parser
          if (id.includes('marked')) return 'marked'
          // Framework runtime — rarely changes, max cache hit
          if (
            id.includes('node_modules/vue') ||
            id.includes('node_modules/vue-router') ||
            id.includes('node_modules/pinia') ||
            id.includes('node_modules/axios') ||
            id.includes('node_modules/@vue')
          ) {
            return 'vendor'
          }
        },
      },
    },
  },
})
