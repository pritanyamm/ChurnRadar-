import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Everything under /api is forwarded to FastAPI, so the browser only ever
    // talks to one origin and we never fight CORS in development.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
