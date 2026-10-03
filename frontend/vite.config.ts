import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * The backend origin the dev server proxies to.
 *
 * The UI always calls same-origin paths (`/api/v1/...`), so the browser never makes a
 * cross-origin request and the backend needs no CORS configuration. Change this one line
 * to point the dev server at a different backend; in a deployment the same paths are
 * served by whatever reverse proxy fronts both the static build and the API.
 */
const backendTarget = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // Bound explicitly: the default `localhost` resolves to IPv6 only on some machines, which
    // makes the documented http://127.0.0.1:5173 unreachable while `localhost` works.
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: backendTarget, changeOrigin: true },
      '/health': { target: backendTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
