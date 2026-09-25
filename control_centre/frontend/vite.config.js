import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Shared by `vite dev` and `vite preview` so the SPA talks to the same backend
// on the same origin in both cases.
const proxy = {
  '/api': {
    target: 'http://127.0.0.1:5001',
    changeOrigin: true,
  },
  '/ws/camera': {
    target: 'ws://127.0.0.1:8766',
    ws: true,
    changeOrigin: true,
  },
  '/ws': {
    target: 'ws://127.0.0.1:8765',
    ws: true,
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy,
  },
  // `vite preview` serves the production build the way nginx does in a real
  // deployment: static SPA with client-side routing, API and both WebSockets
  // on the same origin. This is what the Cloudflare tunnel demo exposes.
  preview: {
    port: 8080,
    host: '127.0.0.1',
    // A tunnel reaches this server under a generated hostname, so the preview
    // server has to accept it. Safe here because it only binds to loopback —
    // the real deployment serves the SPA from nginx, not from Vite.
    allowedHosts: true,
    proxy,
  },
})
