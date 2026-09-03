import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Backend the dev/preview server proxies `/api/*` and `/config.js` to. Point it at a
// remote receiver to run the UI as a client without any CORS setup on the backend:
//   ADSB_API_URL=http://receiver.local:8000 bun run dev
// Read via loadEnv so it can also live in frontend/.env.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = (env.ADSB_API_URL || 'http://localhost:8000').replace(/\/+$/, '')
  const proxy = {
    '/api': { target, changeOrigin: true },
    '/config.js': { target, changeOrigin: true },
  }

  return {
    plugins: [react()],
    server: { port: 3000, host: true, proxy },
    preview: { port: 4173, host: true, proxy },
  }
})
