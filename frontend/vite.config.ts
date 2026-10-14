import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Em dev, /api é encaminhado para o backend Django (mesma origem, sem CORS).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
    },
  },
})
