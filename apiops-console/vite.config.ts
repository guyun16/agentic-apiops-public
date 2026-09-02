import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          changeOrigin: true,
          target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:19090',
        },
        '/actuator': {
          changeOrigin: true,
          target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:19090',
        },
        '/agent-api': {
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/agent-api/, ''),
          target: env.VITE_PYTHON_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        },
      },
    },
  }
})
