import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// In dev/preview the SPA gets its runtime config from this shim instead of
// `adsb start frontend`'s /config.js. apiUrl stays empty: /api/* is proxied below.
const configJs = config => {
  const serve = (_req, res) => {
    res.setHeader('Content-Type', 'application/javascript')
    res.end(`window.APP_CONFIG = ${JSON.stringify({ ...config, apiUrl: '' })};`)
  }
  return {
    name: 'adsb-config-js',
    configureServer(server) {
      server.middlewares.use('/config.js', serve)
    },
    configurePreviewServer(server) {
      server.middlewares.use('/config.js', serve)
    },
  }
}

// Backend the dev/preview server proxies `/api/*` to. Point it at a remote
// receiver to develop the UI against real data:
//   ADSB_API_URL=http://receiver.local:8000 bun run dev
// Or skip the backend entirely with simulated traffic:
//   bun run dev:demo   (vite --mode demo)
export default defineConfig(({ mode }) => {
  // Same MAPBOX_TOKEN and .env the backend uses: the repo-root .env, with a
  // frontend/.env (or VITE_-prefixed variable) still honoured if present.
  const env = { ...loadEnv(mode, repoRoot, ''), ...loadEnv(mode, process.cwd(), '') }
  const target = (env.ADSB_API_URL || 'http://localhost:8000').replace(/\/+$/, '')
  const proxy = { '/api': { target, changeOrigin: true } }
  const mapboxToken = env.MAPBOX_TOKEN || env.VITE_MAPBOX_TOKEN || ''
  const config = { mapboxToken, demo: mode === 'demo' }

  return {
    plugins: [react(), configJs(config)],
    server: { port: 3000, host: true, proxy },
    preview: { port: 4173, host: true, proxy },
  }
})
