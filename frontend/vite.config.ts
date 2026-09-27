import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

const proxy = {
  '/api': { target: process.env.MINI_AGENT_BACKEND_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
}

export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  test: { environment: 'jsdom', clearMocks: true, restoreMocks: true },
})
