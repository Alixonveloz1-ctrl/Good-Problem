import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The PWA and the API are one Cloud Run service, so in development the dev
// server proxies to the backend running on 8080 and in production the built
// assets are served by FastAPI itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/media': 'http://127.0.0.1:8080',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
