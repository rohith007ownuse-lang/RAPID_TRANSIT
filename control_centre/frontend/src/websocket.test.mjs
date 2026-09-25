import { test } from 'node:test'
import assert from 'node:assert/strict'

const { buildSocketUrl } = await import('./websocket.js')

function at(href) {
  globalThis.window = { location: new URL(href) }
}

test('dev fallback targets the backend port, not the page port', () => {
  at('http://localhost:5173/')
  assert.equal(buildSocketUrl('/', 8765, {}), 'ws://localhost:8765/')
  assert.equal(buildSocketUrl('/camera', 8766, {}), 'ws://localhost:8766/camera')
})

test('VITE_WS_PATH keeps both sockets on the page origin and port', () => {
  at('https://demo.example/')
  const env = { VITE_WS_PATH: '/ws' }
  assert.equal(buildSocketUrl('/', 8765, env), 'wss://demo.example/ws/')
  assert.equal(buildSocketUrl('/camera', 8766, env), 'wss://demo.example/ws/camera')
})

test('VITE_WS_URL supports a split host and upgrades to wss', () => {
  at('https://app.vercel.app/')
  const env = { VITE_WS_URL: 'https://api.example.com' }
  assert.equal(buildSocketUrl('/', 8765, env), 'wss://api.example.com:8765/')
  assert.equal(buildSocketUrl('/camera', 8766, env), 'wss://api.example.com:8766/camera')
})

test('VITE_WS_URL wins over VITE_WS_PATH and the socket port replaces the base port', () => {
  at('http://localhost:5173/')
  const env = { VITE_WS_URL: 'http://api.local:8080/', VITE_WS_PATH: '/ws' }
  assert.equal(buildSocketUrl('/camera', 8766, env), 'ws://api.local:8766/camera')
  assert.equal(buildSocketUrl('/', 8765, env), 'ws://api.local:8765/')
})

test('an https page never yields a mixed-content ws:// URL', () => {
  at('https://demo.example/')
  assert.match(buildSocketUrl('/', 8765, {}), /^wss:\/\//)
  assert.match(buildSocketUrl('/', 8765, { VITE_WS_URL: 'https://api.example.com' }), /^wss:\/\//)
})

test('no window falls back to loopback', () => {
  delete globalThis.window
  assert.equal(buildSocketUrl('/', 8765, {}), 'ws://127.0.0.1:8765/')
  assert.equal(buildSocketUrl('/camera', 8766, { VITE_WS_PATH: '/ws' }), 'ws://127.0.0.1/ws/camera')
})
